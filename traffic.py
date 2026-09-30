"""
Live traffic: how busy is a public number *right now*?

* parse_age()      "5 minutes ago" / "Just now" / "2024-05-01 12:30"  -> seconds
* probe_many()     reads several inboxes in parallel, returns Activity per number
* live_feed()      freshest SMS seen across sources (the "Live traffic" screen)

Everything is cached for CACHE_TTL seconds so button-mashing never hammers the
free sites.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import scrapers
from scrapers import SmsMessage

log = logging.getLogger("traffic")

CACHE_TTL = 60.0
PROBE_TIMEOUT = 12.0
CONCURRENCY = 6

FRESH = 15 * 60        # 🟢  newest SMS within 15 min
WARM = 2 * 3600        # 🟡  within 2 h  (otherwise 🔴)

_UNITS = {
    "s": 1, "sec": 1, "second": 1,
    "m": 60, "min": 60, "minute": 60,
    "h": 3600, "hr": 3600, "hour": 3600,
    "d": 86400, "day": 86400,
    "w": 604800, "week": 604800,
    "mo": 2592000, "month": 2592000,
    "y": 31536000, "yr": 31536000, "year": 31536000,
}

_REL_RE = re.compile(r"^(?:about\s+)?(an?|\d+)\s*([a-z]+?)s?\s+ago$")
_ABS_FORMATS = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y/%m/%d %H:%M:%S",
)


def parse_age(text: str) -> int | None:
    """Age in seconds of a site-provided time string, or None if unknown."""
    s = re.sub(r"\s+", " ", (text or "").strip().lower())
    if not s:
        return None
    if s in {"just now", "now", "a moment ago", "moments ago", "few seconds ago", "a few seconds ago"}:
        return 0
    m = _REL_RE.match(s)
    if m:
        n = 1 if m.group(1) in ("a", "an") else int(m.group(1))
        unit = _UNITS.get(m.group(2))
        return n * unit if unit else None
    for fmt in _ABS_FORMATS:                      # absolute stamps: assume UTC
        try:
            dt = datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
            return max(0, int(time.time() - dt.timestamp()))
        except ValueError:
            continue
    return None


def fmt_age(sec: int | None) -> str:
    if sec is None:
        return "?"
    if sec < 60:
        return "now"
    for size, label in ((31536000, "y"), (86400, "d"), (3600, "h"), (60, "m")):
        if sec >= size:
            return f"{sec // size}{label}"
    return "now"


def badge_for_age(age: int | None) -> str:
    if age is None:
        return "🔴"
    return "🟢" if age <= FRESH else "🟡" if age <= WARM else "🔴"


@dataclass
class Activity:
    messages: list[SmsMessage] = field(default_factory=list)   # newest first, as listed
    ages: list[int | None] = field(default_factory=list)       # parallel to messages
    ok: bool = True

    @property
    def count(self) -> int:
        return len(self.messages)

    @property
    def newest(self) -> int | None:
        known = [a for a in self.ages if a is not None]
        return min(known) if known else None

    @property
    def recent(self) -> int:
        """Messages received within the last hour."""
        return sum(1 for a in self.ages if a is not None and a <= 3600)

    @property
    def badge(self) -> str:
        n = self.newest
        if n is None:
            return "🔴"
        return "🟢" if n <= FRESH else "🟡" if n <= WARM else "🔴"

    @property
    def score(self) -> tuple:
        """Sort key: freshest first, then the busiest."""
        n = self.newest
        return (n if n is not None else 10**12, -self.recent)


_cache: dict[tuple[int, str], tuple[float, Activity]] = {}


def cached(src_idx: int, number: str) -> Activity | None:
    hit = _cache.get((src_idx, number))
    if hit and time.time() - hit[0] < CACHE_TTL * 5:     # badges stay visible a few min
        return hit[1]
    return None


async def probe(src_idx: int, number: str, key: str | None, force: bool = False,
                max_age: float = CACHE_TTL) -> Activity:
    hit = _cache.get((src_idx, number))
    if hit and not force and time.time() - hit[0] < max_age:
        return hit[1]
    src = scrapers.SOURCES[src_idx]
    try:
        msgs = await asyncio.wait_for(src.get_messages(number, key), PROBE_TIMEOUT)
        act = Activity(messages=msgs, ages=[parse_age(m.time) for m in msgs])
    except Exception as e:                                # a dead number must not break the batch
        log.info("probe %s %s failed: %s", src.name, number, e)
        act = Activity(ok=False)
    _cache[(src_idx, number)] = (time.time(), act)
    if len(_cache) > 2000:                                # keep memory bounded
        for k in sorted(_cache, key=lambda k: _cache[k][0])[:500]:
            _cache.pop(k, None)
    return act


async def probe_many(entries: list[tuple[int, str, str, str]], limit: int = 24,
                     force: bool = False, max_age: float = CACHE_TTL) -> dict[tuple[int, str], Activity]:
    """entries: (src_idx, number, country, key).  Probes the first `limit`."""
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(e):
        async with sem:
            return (e[0], e[1]), await probe(e[0], e[1], e[3], force, max_age)

    pairs = await asyncio.gather(*[one(e) for e in entries[:limit]])
    return dict(pairs)


def sort_by_activity(entries: list[tuple[int, str, str, str]]) -> list[tuple[int, str, str, str]]:
    """Probed numbers first (freshest → oldest), unprobed ones keep their order after."""
    probed, rest = [], []
    for e in entries:
        act = cached(e[0], e[1])
        (probed if act and act.ok else rest).append(e)
    probed.sort(key=lambda e: cached(e[0], e[1]).score)
    return probed + rest


# ---------------------------------------------------------------------------
# global live feed
# ---------------------------------------------------------------------------

@dataclass
class FeedItem:
    age: int
    sender: str
    text: str
    entry: tuple[int, str, str, str]      # (src_idx, number, country, key)


async def live_feed(entries: list[tuple[int, str, str, str]], max_age: int = 3600,
                    limit: int = 12, probe_limit: int = 30) -> list[FeedItem]:
    acts = await probe_many(entries, limit=probe_limit, max_age=20)   # 'live' = at most 20 s old
    items: list[FeedItem] = []
    for e in entries[:probe_limit]:
        act = acts.get((e[0], e[1]))
        if not act or not act.ok:
            continue
        for m, age in zip(act.messages, act.ages):
            if age is not None and age <= max_age:
                items.append(FeedItem(age=age, sender=m.sender, text=m.text, entry=e))
    items.sort(key=lambda i: i.age)
    return items[:limit]
