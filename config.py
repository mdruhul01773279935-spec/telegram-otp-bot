"""
Configuration for the Free OTP Telegram Bot.

Everything can be overridden with environment variables.
"""

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Minimal .env loader (no extra dependency). Real env vars win."""
    path = Path(__file__).resolve().parent / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), v)


_load_dotenv()


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


# --- REQUIRED ---------------------------------------------------------------
# Get it from @BotFather -> /newbot -> copy the token.
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE").strip()

# Your Telegram user id (optional but recommended) -> grants /stats.
# Get your id from @userinfobot or @getidsbot.
ADMIN_IDS = {
    int(x.strip())
    for x in os.environ.get("ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}

# --- Timing -----------------------------------------------------------------
# How often (seconds) the bot re-checks the inbox for a new SMS.
POLL_INTERVAL = _env_int("POLL_INTERVAL", 8)

# How long (seconds) the bot keeps watching one number before auto-stopping.
DEFAULT_WATCH_SECONDS = _env_int("DEFAULT_WATCH_SECONDS", 15 * 60)

# Extra time granted by the "Extend" button (seconds).
EXTEND_SECONDS = _env_int("EXTEND_SECONDS", 10 * 60)

# Hard cap for one watcher, even after several "Extend" presses (seconds).
MAX_WATCH_SECONDS = _env_int("MAX_WATCH_SECONDS", 60 * 60)

# --- Limits -----------------------------------------------------------------
# Max numbers a single user may watch at the same time.
MAX_ACTIVE_PER_USER = _env_int("MAX_ACTIVE_PER_USER", 2)

# Numbers shown per page in the number-selection menu.
NUMBERS_PER_PAGE = _env_int("NUMBERS_PER_PAGE", 10)

# Max numbers loaded per country from ONE source (sites paginate; we follow pages).
MAX_NUMBERS_PER_COUNTRY = _env_int("MAX_NUMBERS_PER_COUNTRY", 120)
# Max listing pages fetched per country per source.
MAX_PAGES = _env_int("MAX_PAGES", 6)
# Background check that hides countries with no numbers (minutes).
WARMUP_INTERVAL_MIN = _env_int("WARMUP_INTERVAL_MIN", 30)

# How many consecutive fetch failures are tolerated before a source is
# considered down for the current watcher.
MAX_CONSECUTIVE_ERRORS = _env_int("MAX_CONSECUTIVE_ERRORS", 5)

# --- Storage ----------------------------------------------------------------
# Plain JSONL file where received OTPs are logged (/history command).
HISTORY_FILE = os.environ.get("HISTORY_FILE", "otp_history.jsonl")

# --- HTTP -------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 15  # seconds

# Some free hosts (Render/Koyeb/...) require a web port. If PORT is set the bot
# also serves a tiny "OK" page there (use it for uptime pingers).
PORT = _env_int("PORT", 0)
