"""
Tiny JSONL store for received messages (used by /history and /stats).
Nothing sensitive: senders, numbers, message bodies, timestamps.
"""

from __future__ import annotations

import json
import os
import time

from config import HISTORY_FILE

_records: list[dict] = []
_loaded = False
MAX_KEEP = 5000          # records kept in memory


def _load() -> None:
    global _records, _loaded
    if _loaded:
        return
    _loaded = True
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, encoding="utf-8") as f:
                _records = [json.loads(line) for line in f if line.strip()][-MAX_KEEP:]
        except Exception:
            _records = []


def log_sms(chat_id: int, username: str, source: str, number: str, msg_text: str) -> None:
    _load()
    rec = {
        "ts": int(time.time()),
        "chat_id": chat_id,
        "username": username or "",
        "source": source,
        "number": number,
        "sms": msg_text[:500],
    }
    _records.append(rec)
    del _records[:-MAX_KEEP]
    try:
        with open(HISTORY_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def recent_for(chat_id: int, limit: int = 10) -> list[dict]:
    _load()
    return [r for r in _records if r.get("chat_id") == chat_id][-limit:]


def totals() -> dict:
    _load()
    return {"messages": len(_records), "users": len({r.get("chat_id") for r in _records})}
