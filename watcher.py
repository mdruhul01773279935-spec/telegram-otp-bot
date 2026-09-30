"""
SmsWatcher: polls a number's public inbox every POLL_INTERVAL seconds and
forwards newly arrived messages to the user's chat.  One asyncio task per
active number.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field

from config import (
    DEFAULT_WATCH_SECONDS,
    EXTEND_SECONDS,
    MAX_CONSECUTIVE_ERRORS,
    MAX_WATCH_SECONDS,
    POLL_INTERVAL,
)
from scrapers import BaseSource, SmsMessage, SourceError

log = logging.getLogger("watcher")


@dataclass
class Watcher:
    wid: str
    chat_id: int
    source: BaseSource
    number: str
    country: str
    source_key: str | None = None       # slug needed by some sources
    seconds_left: int = DEFAULT_WATCH_SECONDS
    seen: Counter = field(default_factory=Counter)   # message key -> how many seen
    baseline_done: bool = False
    task: asyncio.Task | None = None
    status_msg_id: int | None = None    # "watching..." message that gets edited
    started_at: float = field(default_factory=time.time)

    @property
    def label(self) -> str:
        return f"<b>{self.source.name}</b> — {self.number}"


class WatcherManager:
    def __init__(self) -> None:
        self._watchers: dict[str, Watcher] = {}

    # -- lookup ------------------------------------------------------------
    def get(self, wid: str) -> Watcher | None:
        return self._watchers.get(wid)

    def by_user(self, chat_id: int) -> list[Watcher]:
        return [w for w in self._watchers.values() if w.chat_id == chat_id]

    def active_count(self) -> int:
        return len(self._watchers)

    # -- lifecycle ---------------------------------------------------------
    async def start(
        self,
        chat_id: int,
        source: BaseSource,
        number: str,
        country: str,
        source_key: str | None,
        on_message,
        on_done,
    ) -> Watcher:
        """Create a watcher and launch its polling task.

        on_message(watcher, msg) -> coroutine  (send to chat)
        on_done(watcher, reason) -> coroutine  (final status message)
        """
        w = Watcher(
            wid=uuid.uuid4().hex[:10],
            chat_id=chat_id,
            source=source,
            number=number,
            country=country,
            source_key=source_key,
        )
        w.task = asyncio.create_task(
            self._run(w, on_message, on_done), name=f"watcher-{w.wid}"
        )
        self._watchers[w.wid] = w
        return w

    async def stop(self, wid: str, reason: str = "stopped") -> Watcher | None:
        w = self._watchers.pop(wid, None)
        if w and w.task:
            w.task.cancel()
            if w.task is not asyncio.current_task():
                try:
                    await w.task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    pass
            log.info("watcher %s %s: %s", wid, w.number, reason)
        return w

    async def stop_user(self, chat_id: int) -> int:
        n = 0
        for w in list(self.by_user(chat_id)):
            await self.stop(w.wid, "user stopped all")
            n += 1
        return n

    async def extend(self, wid: str, seconds: int = EXTEND_SECONDS) -> Watcher | None:
        w = self._watchers.get(wid)
        if w:
            w.seconds_left = min(w.seconds_left + seconds, MAX_WATCH_SECONDS)
        return w

    def stop_all(self) -> None:
        for w in list(self._watchers.values()):
            if w.task:
                w.task.cancel()
        self._watchers.clear()

    # -- internals ---------------------------------------------------------
    async def _run(self, w: Watcher, on_message, on_done) -> None:
        consecutive_errors = 0
        # Baseline: whatever is already in the inbox is NOT forwarded.
        # If it fails, the first *successful* fetch becomes the baseline so the
        # user is never flooded with old messages.
        try:
            await self._fetch(w)
            w.baseline_done = True
        except Exception as e:
            log.info("watcher %s baseline failed: %s", w.wid, e)
        try:
            while w.seconds_left > 0:
                step = min(POLL_INTERVAL, w.seconds_left)
                await asyncio.sleep(step)
                w.seconds_left -= step
                try:
                    new_msgs = await self._fetch(w)
                    consecutive_errors = 0
                    if not w.baseline_done:
                        w.baseline_done = True          # swallow old messages
                        continue
                    for m in new_msgs:
                        await on_message(w, m)
                except SourceError as e:
                    consecutive_errors += 1
                    log.warning("watcher %s fetch error: %s", w.wid, e)
                    if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                        self._watchers.pop(w.wid, None)
                        await on_done(w, "source_down")
                        return
                except asyncio.CancelledError:
                    raise
                except Exception as e:  # defensive: never kill the task silently
                    log.exception("watcher %s unexpected error", w.wid)
                    self._watchers.pop(w.wid, None)
                    await on_done(w, "unexpected_error", error=str(e))
                    return
            self._watchers.pop(w.wid, None)
            await on_done(w, "time_up")
        except asyncio.CancelledError:
            raise

    async def _fetch(self, w: Watcher) -> list[SmsMessage]:
        """Return messages that are new since the last fetch (oldest first).

        Counting (instead of a plain set) means that the same text arriving
        twice - e.g. a resent OTP - is still forwarded the second time.
        """
        msgs = await w.source.get_messages(w.number, w.source_key)
        current: Counter = Counter()
        new: list[SmsMessage] = []
        for m in msgs:                                   # sites list newest first
            current[m.key] += 1
            if current[m.key] > w.seen[m.key]:
                new.append(m)
        for k, n in current.items():
            if n > w.seen[k]:
                w.seen[k] = n
        new.reverse()                                    # deliver oldest first
        return new
