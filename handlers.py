"""
Telegram handlers: the whole user flow lives here.

Flow:  /start -> choose source (or Auto) -> choose country -> pick number
       -> watcher forwards every new SMS on that number to the chat.

All user-facing text goes through lang.tr(chat_id, key) — English & Bengali.
"""

from __future__ import annotations

import asyncio
import difflib
import hashlib
import itertools
import logging
import re
import time

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    CallbackQuery,
    ErrorEvent,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import storage
import traffic
from config import (
    ADMIN_IDS,
    MAX_ACTIVE_PER_USER,
    NUMBERS_PER_PAGE,
)
from lang import get_lang, set_lang, tr
from scrapers import SOURCES, SourceError, html_escape, pretty_number
from watcher import WatcherManager

log = logging.getLogger("handlers")

router = Router()

manager = WatcherManager()

# in-memory per-chat state (resets when the bot restarts — fine)
_countries_cache: dict[int, dict[int, tuple[float, dict[str, str]]]] = {}
_numbers_cache: dict[int, dict[str, tuple[float, list]]] = {}
_cur_list: dict[int, list[tuple[int, str, str, str]]] = {}  # chat -> [(src_idx, number, country, key)]

# what the number list on screen belongs to: (country, source name or None, back callback)
_cur_meta: dict[int, tuple[str, str | None, str]] = {}

_auto_merged: dict[int, dict[str, int]] = {}    # chat -> {country: number of sources}

CACHE_TTL = 300.0
COUNTRIES_PER_PAGE = 12
AUTO_PER_PAGE = 12
LIVE_WINDOW = 3600                               # live feed looks at the last hour

# shown first in Auto mode and sampled for the live feed
POPULAR = [
    "United States", "United Kingdom", "Canada", "Sweden", "Finland", "Netherlands",
    "Germany", "France", "India", "Malaysia", "Australia", "Indonesia",
]

# search shortcuts: what people type -> what sites call it
ALIASES = {
    "usa": "united states", "us": "united states", "america": "united states",
    "uk": "united kingdom", "britain": "united kingdom", "england": "united kingdom",
    "gb": "united kingdom", "uae": "united arab emirates", "emirates": "united arab emirates",
    "bd": "bangladesh", "ksa": "saudi arabia", "korea": "south korea",
    "holland": "netherlands", "czechia": "czech republic", "burma": "myanmar",
}

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _fmt_count(n: int) -> str:
    return f"{n/1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def _merged_totals(merged: dict[str, list[tuple[int, str]]]) -> dict[str, int]:
    """country -> total numbers advertised across all sources (1 when a site doesn't say)."""
    return {n: sum(max(1, SOURCES[i].counts.get(n, 1)) for i, _k in v) for n, v in merged.items()}


def _cid(name: str) -> str:
    """Short stable id for a country name (Telegram callback_data max is 64 bytes)."""
    return hashlib.md5(name.encode("utf-8")).hexdigest()[:10]


def _resolve_country(names, cid: str) -> str | None:
    return next((n for n in names if _cid(n) == cid), None)


def _cb(builder: InlineKeyboardBuilder, text: str, data: str) -> None:
    builder.add(InlineKeyboardButton(text=text, callback_data=data))


def _back_button(chat_id: int, data: str) -> InlineKeyboardBuilder:
    b = InlineKeyboardBuilder()
    _cb(b, tr(chat_id, "btn_back"), data)
    return b


def _main_menu(chat_id: int) -> InlineKeyboardMarkup:
    b = InlineKeyboardBuilder()
    _cb(b, tr(chat_id, "btn_get_number"), "src:-1")
    _cb(b, tr(chat_id, "btn_live"), "live:go")
    _cb(b, tr(chat_id, "btn_search"), "find:go")
    _cb(b, tr(chat_id, "btn_active"), "active:list")
    _cb(b, tr(chat_id, "btn_stop_all"), "stopall")
    _cb(b, tr(chat_id, "btn_lang"), "lang:pick")
    _cb(b, tr(chat_id, "btn_help"), "help:1")
    b.adjust(1)
    return b.as_markup()


def _stop_buttons(chat_id: int, wid: str, from_sms: bool = False) -> InlineKeyboardMarkup:
    """Stop / extend buttons.  Buttons on an SMS message carry a ':s' suffix so
    pressing them never overwrites the SMS text (the OTP!)."""
    suffix = ":s" if from_sms else ""
    b = InlineKeyboardBuilder()
    _cb(b, tr(chat_id, "btn_stop"), f"stop:{wid}{suffix}")
    _cb(b, tr(chat_id, "btn_extend"), f"ext:{wid}{suffix}")
    b.adjust(2)
    return b.as_markup()


async def _edit_status(bot: Bot, chat_id: int, w, text: str, markup: InlineKeyboardMarkup | None) -> None:
    """Update the watcher's own 'watching…' status message (if we know it)."""
    if w.status_msg_id is None:
        return
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=w.status_msg_id,
                                    reply_markup=markup, parse_mode="HTML")
    except Exception:
        pass   # not modified / message deleted


async def _fetch_countries(chat_id: int, idx: int, force: bool = False) -> dict[str, str]:
    now = time.time()
    cached = _countries_cache.get(chat_id, {}).get(idx)
    if cached and not force and now - cached[0] < CACHE_TTL:
        return cached[1]
    src = SOURCES[idx]
    countries = await src.list_countries()
    _countries_cache.setdefault(chat_id, {})[idx] = (now, countries)
    return countries


async def _fetch_numbers(chat_id: int, idx: int, country: str, force: bool = False) -> list:
    key = f"{idx}|{country}"
    now = time.time()
    cached = _numbers_cache.get(chat_id, {}).get(key)
    if cached and not force and now - cached[0] < CACHE_TTL:
        return cached[1]
    src = SOURCES[idx]
    numbers = await src.list_numbers(country)
    _numbers_cache.setdefault(chat_id, {})[key] = (now, numbers)
    return numbers


def _countries_keyboard(chat_id: int, idx: int, countries: dict[str, str], page: int = 0) -> InlineKeyboardMarkup:
    counts = SOURCES[idx].counts
    items = sorted(countries.items(), key=lambda kv: (-counts.get(kv[0], 0), kv[0].lower()))
    pages = max(1, (len(items) + COUNTRIES_PER_PAGE - 1) // COUNTRIES_PER_PAGE)
    page = max(0, min(page, pages - 1))
    start, end = page * COUNTRIES_PER_PAGE, (page + 1) * COUNTRIES_PER_PAGE
    b = InlineKeyboardBuilder()
    shown = items[start:end]
    for name, _key in shown:
        c = counts.get(name)
        _cb(b, f"🌍 {name}" + (f" · {_fmt_count(c)}" if c else ""), f"ctr:{idx}:{_cid(name)}")
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"cpg:{idx}:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="none"))
    if end < len(items):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"cpg:{idx}:{page+1}"))
    b.row(*nav)
    b.row(InlineKeyboardButton(text=tr(chat_id, "btn_search"), callback_data="find:go"))
    b.row(InlineKeyboardButton(text=tr(chat_id, "btn_back_sources"), callback_data="src:-1"))
    # NOTE: adjust() re-flows *all* buttons, so give it the exact row sizes
    b.adjust(*([1] * len(shown)), len(nav), 1, 1)
    return b.as_markup()


def _number_label(src_idx: int, number: str) -> str:
    act = traffic.cached(src_idx, number)
    label = pretty_number(number)
    if act is None:
        hint = getattr(SOURCES[src_idx], "age_hint", {}).get(number)     # site-provided "last activity"
        if hint:
            age = traffic.parse_age(hint)
            return f"{traffic.badge_for_age(age)} {label} · {traffic.fmt_age(age)}"
        return label
    if not act.ok:
        return f"⚪ {label}"
    extra = f" · {traffic.fmt_age(act.newest)}" if act.newest is not None else ""
    if act.recent:
        extra += f" · {act.recent}💬"
    return f"{act.badge} {label}{extra}"


def _numbers_keyboard(chat_id: int, page: int = 0) -> InlineKeyboardMarkup:
    entries = _cur_list.get(chat_id, [])
    pages = max(1, (len(entries) + NUMBERS_PER_PAGE - 1) // NUMBERS_PER_PAGE)
    page = max(0, min(page, pages - 1))
    start, end = page * NUMBERS_PER_PAGE, (page + 1) * NUMBERS_PER_PAGE
    b = InlineKeyboardBuilder()
    shown = entries[start:end]
    for src_idx, number, _country, _key in shown:
        b.add(InlineKeyboardButton(text=_number_label(src_idx, number), callback_data=f"num:{src_idx}:{number}"))
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"pg:back:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="none"))
    if end < len(entries):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"pg:fwd:{page+1}"))
    b.row(*nav)
    b.row(InlineKeyboardButton(text=tr(chat_id, "btn_sort_live"), callback_data="live:sort"))
    back = _cur_meta.get(chat_id, ("", None, "auto:go"))[2]
    b.row(InlineKeyboardButton(text=tr(chat_id, "btn_back"), callback_data=back))
    sizes = []
    left = len(shown)
    while left > 0:
        sizes.append(min(1, left))          # badges make labels long -> one per row
        left -= 1
    b.adjust(*sizes, len(nav), 1, 1)
    return b.as_markup()


def _numbers_title(chat_id: int, n: int) -> str:
    country, source, _back = _cur_meta.get(chat_id, ("", None, "auto:go"))
    if source:
        title = tr(chat_id, "numbers_title", country=country, source=source, count=n)
    else:
        title = tr(chat_id, "numbers_title_auto", country=country, count=n)
    entries = _cur_list.get(chat_id, [])
    if any(traffic.cached(e[0], e[1]) for e in entries[:NUMBERS_PER_PAGE]):
        title += tr(chat_id, "sorted_note")
    return title


async def _edit_or_answer(q: CallbackQuery, text: str, markup: InlineKeyboardMarkup | None):
    try:
        return await q.message.edit_text(text, reply_markup=markup, parse_mode="HTML")
    except TelegramBadRequest as e:
        if "message is not modified" in str(e).lower():
            return q.message
        return await q.message.answer(text, reply_markup=markup, parse_mode="HTML")
    except Exception:
        return await q.message.answer(text, reply_markup=markup, parse_mode="HTML")


# ---------------------------------------------------------------------------
# basic commands
# ---------------------------------------------------------------------------

@router.message(CommandStart())
async def cmd_start(m: Message):
    await m.answer(tr(m.chat.id, "start"), reply_markup=_main_menu(m.chat.id))


@router.message(Command("help"))
async def cmd_help(m: Message):
    await m.answer(tr(m.chat.id, "help"))


@router.message(Command("lang"))
async def cmd_lang(m: Message):
    b = InlineKeyboardBuilder()
    _cb(b, tr(m.chat.id, "lang_en"), "lang:en")
    _cb(b, tr(m.chat.id, "lang_bn"), "lang:bn")
    b.adjust(2)
    await m.answer(tr(m.chat.id, "choose_lang"), reply_markup=b.as_markup())


@router.message(Command("active"))
async def cmd_active(m: Message):
    await _show_active(m.chat.id, m)


async def _show_active(chat_id: int, m: Message | None = None, q: CallbackQuery | None = None):
    watchers = manager.by_user(chat_id)
    if not watchers:
        text = tr(chat_id, "active_none")
    else:
        lines = [tr(chat_id, "active_title", count=len(watchers), limit=MAX_ACTIVE_PER_USER)]
        for w in watchers:
            lines.append(
                tr(chat_id, "active_line",
                   number=pretty_number(w.number),
                   source=w.source.name,
                   minutes=max(0, w.seconds_left) // 60)
            )
        text = "\n".join(lines)
    b = InlineKeyboardBuilder()
    for w in watchers:
        _cb(b, f"⏹ {pretty_number(w.number)}", f"stop:{w.wid}")
    _cb(b, tr(chat_id, "btn_new_number"), "src:-1")
    b.adjust(1)
    if m:
        await m.answer(text, reply_markup=b.as_markup())
    elif q:
        await _edit_or_answer(q, text, b.as_markup())


@router.message(Command("stopall"))
async def cmd_stopall(m: Message):
    n = await manager.stop_user(m.chat.id)
    await m.answer(tr(m.chat.id, "stopall_done", count=n))


@router.message(Command("history"))
async def cmd_history(m: Message):
    recs = storage.recent_for(m.chat.id, limit=10)
    if not recs:
        await m.answer(tr(m.chat.id, "history_none"))
        return
    lines = [tr(m.chat.id, "history_title")]
    for r in reversed(recs):
        ts = time.strftime("%H:%M %d.%m", time.localtime(r["ts"]))
        lines.append(
            tr(m.chat.id, "history_line",
               ts=ts, number=html_escape(pretty_number(r["number"])),
               source=html_escape(r["source"]), sms=html_escape(r["sms"][:60]))
        )
    await m.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("stats"))
async def cmd_stats(m: Message):
    if m.chat.id not in ADMIN_IDS:
        await m.answer(tr(m.chat.id, "not_authorized"))
        return
    t = storage.totals()
    await m.answer(
        tr(m.chat.id, "stats_title",
           active=manager.active_count(),
           messages=t["messages"],
           users=t["users"])
    )


@router.message(Command("ping"))
async def cmd_ping(m: Message):
    await m.answer(tr(m.chat.id, "ping"))


# ---------------------------------------------------------------------------
# callbacks
# ---------------------------------------------------------------------------

@router.callback_query(F.data == "none")
async def cb_none(q: CallbackQuery):
    await q.answer()


@router.callback_query(F.data == "help:1")
async def cb_help(q: CallbackQuery):
    await q.answer()
    await _edit_or_answer(q, tr(q.message.chat.id, "help"), _back_button(q.message.chat.id, "src:-1").as_markup())


@router.callback_query(F.data == "active:list")
async def cb_active(q: CallbackQuery):
    await q.answer()
    await _show_active(q.message.chat.id, q=q)


@router.callback_query(F.data == "stopall")
async def cb_stopall(q: CallbackQuery):
    await q.answer()
    n = await manager.stop_user(q.message.chat.id)
    await _edit_or_answer(q, tr(q.message.chat.id, "stopall_done", count=n), _main_menu(q.message.chat.id))


@router.callback_query(F.data == "lang:pick")
async def cb_lang_pick(q: CallbackQuery):
    await q.answer()
    b = InlineKeyboardBuilder()
    _cb(b, tr(q.message.chat.id, "lang_en"), "lang:en")
    _cb(b, tr(q.message.chat.id, "lang_bn"), "lang:bn")
    b.row(InlineKeyboardButton(text=tr(q.message.chat.id, "btn_main_menu"), callback_data="menu:main"))
    b.adjust(2, 1)
    await _edit_or_answer(q, tr(q.message.chat.id, "choose_lang"), b.as_markup())


@router.callback_query(F.data.startswith("lang:"))
async def cb_lang_set(q: CallbackQuery):
    lang = q.data.split(":")[1]
    if lang not in ("en", "bn"):
        return
    set_lang(q.message.chat.id, lang)
    await q.answer()
    await _edit_or_answer(
        q,
        tr(q.message.chat.id, "lang_set", lang="English 🇬🇧" if lang == "en" else "বাংলা 🇧🇩"),
        _main_menu(q.message.chat.id),
    )


@router.callback_query(F.data == "src:-1")
async def cb_sources(q: CallbackQuery):
    """List of sources (+ Auto)."""
    await q.answer()
    chat_id = q.message.chat.id
    b = InlineKeyboardBuilder()
    _cb(b, tr(chat_id, "btn_auto"), "auto:go")
    for idx, src in enumerate(SOURCES):
        _cb(b, f"🌐 {src.name}", f"src:{idx}")
    _cb(b, tr(chat_id, "btn_main_menu"), "menu:main")
    b.adjust(1)
    await _edit_or_answer(q, tr(chat_id, "choose_source"), b.as_markup())


def _rows(n: int, per: int) -> list[int]:
    return [per] * (n // per) + ([n % per] if n % per else [])


def _auto_keyboard(chat_id: int, page: int = 0) -> InlineKeyboardMarkup:
    merged = _auto_merged.get(chat_id, {})
    names = sorted(merged, key=lambda n: (-merged[n], n.lower()))     # most numbers first
    pages = max(1, (len(names) + AUTO_PER_PAGE - 1) // AUTO_PER_PAGE)
    page = max(0, min(page, pages - 1))
    b = InlineKeyboardBuilder()
    sizes: list[int] = []
    _cb(b, tr(chat_id, "btn_search"), "find:go")
    sizes.append(1)
    if page == 0:                                    # ⭐ popular row(s)
        pop = [n for n in POPULAR if n in merged][:6]
        for n in pop:
            _cb(b, f"⭐ {n}", f"actr:{_cid(n)}")
        sizes += _rows(len(pop), 2)
    shown = names[page * AUTO_PER_PAGE:(page + 1) * AUTO_PER_PAGE]
    for n in shown:
        _cb(b, f"🌍 {n} · {_fmt_count(merged[n])}", f"actr:{_cid(n)}")
    sizes += _rows(len(shown), 2)
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"apg:{page-1}"))
    nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data="none"))
    if (page + 1) * AUTO_PER_PAGE < len(names):
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"apg:{page+1}"))
    b.row(*nav)
    sizes.append(len(nav))
    b.row(InlineKeyboardButton(text=tr(chat_id, "btn_back_sources"), callback_data="src:-1"))
    sizes.append(1)
    b.adjust(*sizes)
    return b.as_markup()


async def _gather_countries(chat_id: int, force: bool = False) -> dict[str, list[tuple[int, str]]]:
    merged: dict[str, list[tuple[int, str]]] = {}
    results = await asyncio.gather(
        *[_fetch_countries(chat_id, i, force=force) for i in range(len(SOURCES))],
        return_exceptions=True,
    )
    for idx, res in enumerate(results):
        if isinstance(res, Exception):
            log.warning("countries fetch failed for %s: %s", SOURCES[idx].name, res)
            continue
        for name, key in res.items():
            merged.setdefault(name, []).append((idx, key))
    return merged


@router.callback_query(F.data == "auto:go")
async def cb_auto(q: CallbackQuery):
    await q.answer(tr(q.message.chat.id, "fetching_countries"))
    chat_id = q.message.chat.id
    await q.bot.send_chat_action(chat_id, ChatAction.TYPING)
    merged = await _gather_countries(chat_id)
    if not merged:
        await _edit_or_answer(q, tr(chat_id, "no_countries_anywhere"), _back_button(chat_id, "src:-1").as_markup())
        return
    _cur_list[chat_id] = []  # reset any old number list
    _auto_merged[chat_id] = _merged_totals(merged)
    await _edit_or_answer(q, tr(chat_id, "auto_title", count=len(merged)), _auto_keyboard(chat_id, 0))


@router.callback_query(F.data.startswith("apg:"))
async def cb_auto_page(q: CallbackQuery):
    await q.answer()
    chat_id = q.message.chat.id
    try:
        page = int(q.data.split(":")[1])
    except (ValueError, IndexError):
        page = 0
    if not _auto_merged.get(chat_id):
        _auto_merged[chat_id] = _merged_totals(await _gather_countries(chat_id))
    await _edit_or_answer(
        q, tr(chat_id, "auto_title", count=len(_auto_merged[chat_id])), _auto_keyboard(chat_id, page)
    )


# ---------------------------------------------------------------------------
# country search  (/country sweden  —  or just type a name)
# ---------------------------------------------------------------------------

def _match_countries(query: str, names: list[str]) -> list[str]:
    q = " ".join(query.lower().split())
    q = ALIASES.get(q, q)
    if not q:
        return []
    low = {n.lower(): n for n in names}
    hits: list[str] = []

    def add(n: str) -> None:
        if n not in hits:
            hits.append(n)

    if q in low:
        add(low[q])
    for l, n in sorted(low.items()):
        if l.startswith(q):
            add(n)
    for l, n in sorted(low.items()):
        if q in l:
            add(n)
    for l in difflib.get_close_matches(q, list(low), n=5, cutoff=0.7):
        add(low[l])
    return hits[:10]


async def _search_view(chat_id: int, query: str) -> tuple[str, InlineKeyboardMarkup]:
    merged = await _gather_countries(chat_id)
    _auto_merged[chat_id] = _merged_totals(merged)
    hits = _match_countries(query, list(merged))
    b = InlineKeyboardBuilder()
    if not hits:
        _cb(b, tr(chat_id, "btn_search"), "find:go")
        _cb(b, tr(chat_id, "btn_get_number"), "auto:go")
        b.adjust(1)
        return tr(chat_id, "search_none", query=html_escape(query)), b.as_markup()
    for n in hits:
        _cb(b, f"🌍 {n} · {_fmt_count(_merged_totals({n: merged[n]})[n])}", f"actr:{_cid(n)}")
    _cb(b, tr(chat_id, "btn_main_menu"), "menu:main")
    b.adjust(1)
    return tr(chat_id, "search_results", query=html_escape(query)), b.as_markup()


@router.callback_query(F.data == "find:go")
async def cb_find(q: CallbackQuery):
    await q.answer()
    chat_id = q.message.chat.id
    await _edit_or_answer(q, tr(chat_id, "search_prompt"), _back_button(chat_id, "auto:go").as_markup())


@router.message(Command("country"))
async def cmd_country(m: Message, command: CommandObject):
    query = (command.args or "").strip()[:40]
    if not query:
        await m.answer(tr(m.chat.id, "search_prompt"))
        return
    text, markup = await _search_view(m.chat.id, query)
    await m.answer(text, reply_markup=markup)


# ---------------------------------------------------------------------------
# live traffic
# ---------------------------------------------------------------------------

async def _live_entries(chat_id: int) -> list[tuple[int, str, str, str]]:
    """Sample numbers to probe: a few per popular country, round-robin over sources."""
    merged = await _gather_countries(chat_id)
    pairs = [(i, n, k) for n in POPULAR for (i, k) in merged.get(n, [])]
    # pick countries that other sources cover too, then whatever else exists
    for n in sorted(merged, key=str.lower):
        if n not in POPULAR:
            pairs += [(i, n, k) for (i, k) in merged[n]][:1]
    pairs = pairs[:24]
    results = await asyncio.gather(
        *[_fetch_numbers(chat_id, i, k) for (i, _n, k) in pairs], return_exceptions=True
    )
    per_pair = [
        [(i, num, n, k) for num in res[:3]]
        for (i, n, k), res in zip(pairs, results) if not isinstance(res, Exception)
    ]
    entries, seen = [], set()
    for round_ in range(3):                           # round-robin so every site is sampled
        for lst in per_pair:
            if round_ < len(lst) and (lst[round_][0], lst[round_][1]) not in seen:
                seen.add((lst[round_][0], lst[round_][1]))
                entries.append(lst[round_])
    return entries[:30]


async def _live_view(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    entries = await _live_entries(chat_id)
    feed = await traffic.live_feed(entries, max_age=LIVE_WINDOW, limit=10) if entries else []
    b = InlineKeyboardBuilder()
    if not feed:
        _cb(b, tr(chat_id, "btn_refresh"), "live:go")
        _cb(b, tr(chat_id, "btn_get_number"), "auto:go")
        _cb(b, tr(chat_id, "btn_main_menu"), "menu:main")
        b.adjust(1)
        return tr(chat_id, "live_none"), b.as_markup()
    lines = [tr(chat_id, "live_title", minutes=LIVE_WINDOW // 60), ""]
    picked: list[tuple[int, str, str, str]] = []
    for it in feed:
        src_idx, number, country, _k = it.entry
        badge = "🟢" if it.age <= traffic.FRESH else "🟡"
        lines.append(
            f"{badge} <b>{traffic.fmt_age(it.age)}</b> · {html_escape(it.sender or '?')} → "
            f"{html_escape(pretty_number(number))} <i>({html_escape(country)})</i>\n"
            f"    <i>{html_escape(it.text[:70])}</i>"
        )
        if it.entry not in picked:
            picked.append(it.entry)
    lines += ["", tr(chat_id, "live_legend")]
    _cur_list[chat_id] = picked
    _cur_meta[chat_id] = ("Live traffic", None, "live:go")
    for e in picked[:6]:
        _cb(b, _number_label(e[0], e[1]) + f" · {e[2]}", f"num:{e[0]}:{e[1]}")
    _cb(b, tr(chat_id, "btn_refresh"), "live:go")
    _cb(b, tr(chat_id, "btn_main_menu"), "menu:main")
    b.adjust(1)
    text = "\n".join(lines)
    return text[:4000], b.as_markup()


@router.message(Command("live"))
async def cmd_live(m: Message):
    await m.bot.send_chat_action(m.chat.id, ChatAction.TYPING)
    text, markup = await _live_view(m.chat.id)
    await m.answer(text, reply_markup=markup)


@router.callback_query(F.data == "live:go")
async def cb_live(q: CallbackQuery):
    await q.answer(tr(q.message.chat.id, "live_fetching"))
    chat_id = q.message.chat.id
    await q.bot.send_chat_action(chat_id, ChatAction.TYPING)
    try:
        text, markup = await _live_view(chat_id)
    except Exception as e:
        log.warning("live view failed: %s", e)
        text, markup = tr(chat_id, "live_none"), _main_menu(chat_id)
    await _edit_or_answer(q, text, markup)


@router.callback_query(F.data == "live:sort")
async def cb_live_sort(q: CallbackQuery):
    """Probe the numbers on screen, then show the busiest/freshest first."""
    await q.answer(tr(q.message.chat.id, "live_fetching"))
    chat_id = q.message.chat.id
    entries = _cur_list.get(chat_id, [])
    if not entries:
        await _edit_or_answer(q, tr(chat_id, "menu_stale"), _main_menu(chat_id))
        return
    await q.bot.send_chat_action(chat_id, ChatAction.TYPING)
    await traffic.probe_many(entries, limit=36, force=True)
    _cur_list[chat_id] = traffic.sort_by_activity(entries)
    await _edit_or_answer(q, _numbers_title(chat_id, len(entries)), _numbers_keyboard(chat_id, 0))


@router.callback_query(F.data.startswith("actr:"))
async def cb_auto_country(q: CallbackQuery):
    """Auto mode: pick country -> gather numbers from all sources that have it."""
    await q.answer(tr(q.message.chat.id, "fetching_numbers"))
    chat_id = q.message.chat.id
    await q.bot.send_chat_action(chat_id, ChatAction.TYPING)

    per_source: list[dict[str, str] | Exception] = await asyncio.gather(
        *[_fetch_countries(chat_id, i) for i in range(len(SOURCES))],
        return_exceptions=True,
    )
    all_names = {n for res in per_source if isinstance(res, dict) for n in res}
    name = _resolve_country(all_names, q.data.split(":", 1)[1])
    if name is None:
        await _edit_or_answer(q, tr(chat_id, "country_not_found"), _back_button(chat_id, "auto:go").as_markup())
        return
    targets = [(i, res[name]) for i, res in enumerate(per_source) if isinstance(res, dict) and name in res]

    results = await asyncio.gather(
        *[_fetch_numbers(chat_id, i, k, force=True) for (i, k) in targets],
        return_exceptions=True,
    )
    per_src: list[list[tuple[int, str, str, str]]] = []
    for (i, k), res in zip(targets, results):
        if isinstance(res, Exception):
            log.warning("numbers fetch failed for %s/%s: %s", SOURCES[i].name, name, res)
            continue
        per_src.append([(i, number, name, k) for number in res])
    # round-robin so the first page mixes sources (and "live activity" samples all of them)
    entries = [e for group in itertools.zip_longest(*per_src) for e in group if e is not None]
    if not entries:
        await _edit_or_answer(q, tr(chat_id, "no_numbers_anywhere"), _back_button(chat_id, "auto:go").as_markup())
        return
    _cur_list[chat_id] = entries
    _cur_meta[chat_id] = (name, None, "auto:go")
    await _edit_or_answer(q, _numbers_title(chat_id, len(entries)), _numbers_keyboard(chat_id, 0))


@router.callback_query(F.data.startswith("src:"))
async def cb_countries(q: CallbackQuery):
    await q.answer(tr(q.message.chat.id, "fetching_countries"))
    chat_id = q.message.chat.id
    try:
        idx = int(q.data.split(":")[1])
        src = SOURCES[idx]
    except (ValueError, IndexError):
        await _edit_or_answer(q, tr(chat_id, "menu_stale"), _main_menu(chat_id))
        return
    await q.bot.send_chat_action(chat_id, ChatAction.TYPING)
    try:
        countries = await _fetch_countries(chat_id, idx, force=True)
    except Exception as e:  # SourceError or a parsing problem
        log.warning("countries fetch failed for %s: %s", src.name, e)
        await _edit_or_answer(
            q,
            tr(chat_id, "source_error", source=src.name, error=html_escape(str(e))),
            _back_button(chat_id, "src:-1").as_markup(),
        )
        return
    if not countries:
        await _edit_or_answer(
            q,
            tr(chat_id, "source_no_countries", source=src.name),
            _back_button(chat_id, "src:-1").as_markup(),
        )
        return
    await _edit_or_answer(
        q,
        tr(chat_id, "countries_title", source=src.name, count=len(countries)),
        _countries_keyboard(chat_id, idx, countries, 0),
    )


@router.callback_query(F.data.startswith("cpg:"))
async def cb_countries_page(q: CallbackQuery):
    await q.answer()
    chat_id = q.message.chat.id
    try:
        _, idx_s, page_s = q.data.split(":")
        idx, page = int(idx_s), int(page_s)
        countries = await _fetch_countries(chat_id, idx)
    except Exception as e:
        log.warning("country page failed: %s", e)
        await _edit_or_answer(q, tr(chat_id, "menu_stale"), _main_menu(chat_id))
        return
    await _edit_or_answer(
        q,
        tr(chat_id, "countries_title", source=SOURCES[idx].name, count=len(countries)),
        _countries_keyboard(chat_id, idx, countries, page),
    )


@router.callback_query(F.data.startswith("ctr:"))
async def cb_numbers(q: CallbackQuery):
    await q.answer(tr(q.message.chat.id, "fetching_numbers"))
    chat_id = q.message.chat.id
    try:
        _, idx_s, cid = q.data.split(":", 2)
        idx = int(idx_s)
        src = SOURCES[idx]
    except (ValueError, IndexError):
        await _edit_or_answer(q, tr(chat_id, "menu_stale"), _main_menu(chat_id))
        return
    await q.bot.send_chat_action(chat_id, ChatAction.TYPING)
    try:
        countries = await _fetch_countries(chat_id, idx)
        name = _resolve_country(countries, cid)
        if name is None:                                   # cache expired / list changed
            countries = await _fetch_countries(chat_id, idx, force=True)
            name = _resolve_country(countries, cid)
        if name is None:
            await _edit_or_answer(q, tr(chat_id, "country_not_found"), _back_button(chat_id, f"src:{idx}").as_markup())
            return
        key = countries[name]                              # URL key (slug) for this source
        numbers = await _fetch_numbers(chat_id, idx, key, force=True)
    except Exception as e:
        log.warning("numbers fetch failed for %s: %s", src.name, e)
        await _edit_or_answer(
            q,
            tr(chat_id, "numbers_error", source=src.name, error=html_escape(str(e))),
            _back_button(chat_id, f"src:{idx}").as_markup(),
        )
        return
    if not numbers:
        await _edit_or_answer(
            q,
            tr(chat_id, "no_numbers_country", country=name),
            _back_button(chat_id, f"src:{idx}").as_markup(),
        )
        return
    _cur_list[chat_id] = [(idx, n, name, key) for n in numbers]
    _cur_meta[chat_id] = (name, src.name, f"src:{idx}")
    await _edit_or_answer(q, _numbers_title(chat_id, len(numbers)), _numbers_keyboard(chat_id, 0))


@router.callback_query(F.data.startswith("pg:"))
async def cb_numbers_page(q: CallbackQuery):
    await q.answer()
    chat_id = q.message.chat.id
    try:
        page = int(q.data.split(":")[2])
    except (ValueError, IndexError):
        page = 0
    entries = _cur_list.get(chat_id, [])
    if not entries:
        await _edit_or_answer(q, tr(chat_id, "menu_stale"), _main_menu(chat_id))
        return
    await _edit_or_answer(q, _numbers_title(chat_id, len(entries)), _numbers_keyboard(chat_id, page))


@router.callback_query(F.data.startswith("num:"))
async def cb_pick_number(q: CallbackQuery):
    await q.answer()
    chat_id = q.message.chat.id
    try:
        _, src_s, number = q.data.split(":", 2)
        src_idx = int(src_s)
        src = SOURCES[src_idx]
    except (ValueError, IndexError):
        await _edit_or_answer(q, tr(chat_id, "menu_stale"), _main_menu(chat_id))
        return

    # resolve country/key from the current list
    entry = next(
        (e for e in _cur_list.get(chat_id, []) if e[0] == src_idx and e[1] == number),
        None,
    )
    if entry is None:
        await _edit_or_answer(q, tr(chat_id, "menu_stale"), _main_menu(chat_id))
        return
    _src_idx, _n, country, key = entry

    mine = manager.by_user(chat_id)
    dup = next((w for w in mine if w.number == number and w.source is src), None)
    if dup is not None:                       # already watching it -> just show that watcher
        await _edit_or_answer(
            q,
            tr(chat_id, "watching", number=pretty_number(number), source=src.name,
               minutes=max(0, dup.seconds_left) // 60),
            _stop_buttons(chat_id, dup.wid),
        )
        dup.status_msg_id = q.message.message_id
        return
    if len(mine) >= MAX_ACTIVE_PER_USER:
        await _edit_or_answer(
            q,
            tr(chat_id, "limit_reached", limit=MAX_ACTIVE_PER_USER),
            _main_menu(chat_id),
        )
        return

    bot = q.bot

    async def on_message(w, msg):
        lang = get_lang(chat_id)                       # user may switch language mid-watch
        body = msg.pretty(lang)
        text = tr(chat_id, "new_sms", number=pretty_number(w.number), source=w.source.name, body=body)
        for attempt in range(4):                       # never lose an OTP to a network blip
            try:
                await bot.send_message(
                    chat_id, text,
                    reply_markup=_stop_buttons(chat_id, w.wid, from_sms=True),
                    parse_mode="HTML",
                )
                break
            except TelegramBadRequest:                 # e.g. bad HTML -> resend as plain text
                try:
                    await bot.send_message(chat_id, re.sub(r"<[^>]+>", "", text), parse_mode=None)
                except Exception:
                    log.exception("failed to send message (plain)")
                break
            except Exception as e:
                log.warning("send to %s failed (attempt %d): %s", chat_id, attempt + 1, e)
                await asyncio.sleep(1.5 * (attempt + 1))
        else:
            log.error("giving up sending SMS to %s", chat_id)
        storage.log_sms(chat_id, "", w.source.name, w.number, f"{msg.sender}: {msg.text}")

    async def on_done(w, reason, **kw):
        if "error" in kw:
            kw["error"] = html_escape(str(kw["error"]))
        text = f"👀 <b>{pretty_number(w.number)}</b> ({w.source.name})\n\n{tr(chat_id, reason, **kw)}"
        try:
            if w.status_msg_id is None:
                raise ValueError("no status message")
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=w.status_msg_id,
                reply_markup=_main_menu(chat_id),
                parse_mode="HTML",
            )
        except Exception:
            try:
                await bot.send_message(chat_id, text, reply_markup=_main_menu(chat_id), parse_mode="HTML")
            except Exception:
                log.exception("failed to send final status")

    w = await manager.start(chat_id, src, number, country, key, on_message, on_done)
    w.status_msg_id = q.message.message_id      # the menu message becomes the status message
    minutes = max(0, w.seconds_left) // 60
    status = tr(chat_id, "watching", number=pretty_number(number), source=src.name, minutes=minutes)
    try:
        await q.message.edit_text(status, reply_markup=_stop_buttons(chat_id, w.wid), parse_mode="HTML")
    except Exception:
        sent = await q.message.answer(status, reply_markup=_stop_buttons(chat_id, w.wid), parse_mode="HTML")
        w.status_msg_id = sent.message_id


@router.callback_query(F.data.startswith("stop:"))
async def cb_stop(q: CallbackQuery):
    chat_id = q.message.chat.id
    parts = q.data.split(":")
    wid, from_sms = parts[1], len(parts) > 2
    w = await manager.stop(wid, "user stopped")
    if not w:
        await q.answer(tr(chat_id, "already_stopped"))
        if from_sms:
            try:
                await q.message.edit_reply_markup(reply_markup=None)   # keep the SMS text
            except Exception:
                pass
        else:
            await _edit_or_answer(q, tr(chat_id, "main_menu_title"), _main_menu(chat_id))
        return
    await q.answer()
    text = tr(chat_id, "stopped", number=pretty_number(w.number), source=w.source.name)
    if from_sms:
        await _edit_status(q.bot, chat_id, w, text, _main_menu(chat_id))
        try:
            await q.message.edit_reply_markup(reply_markup=None)       # keep the SMS text
        except Exception:
            pass
        if w.status_msg_id is None:
            await q.message.answer(text, reply_markup=_main_menu(chat_id), parse_mode="HTML")
    else:
        if w.status_msg_id not in (None, q.message.message_id):
            await _edit_status(q.bot, chat_id, w, text, _main_menu(chat_id))
        await _edit_or_answer(q, text, _main_menu(chat_id))


@router.callback_query(F.data.startswith("ext:"))
async def cb_extend(q: CallbackQuery):
    chat_id = q.message.chat.id
    parts = q.data.split(":")
    wid, from_sms = parts[1], len(parts) > 2
    w = await manager.extend(wid)
    if not w:
        await q.answer(tr(chat_id, "already_stopped"))
        return
    minutes = max(0, w.seconds_left) // 60
    text = tr(chat_id, "extended", number=pretty_number(w.number), source=w.source.name, minutes=minutes)
    if from_sms:
        await q.answer(re.sub(r"<[^>]+>", "", text)[:200])
        await _edit_status(q.bot, chat_id, w, text, _stop_buttons(chat_id, w.wid))
    else:
        await q.answer()
        await _edit_or_answer(q, text, _stop_buttons(chat_id, w.wid))


@router.callback_query(F.data == "menu:main")
async def cb_menu_main(q: CallbackQuery):
    await q.answer()
    await _edit_or_answer(q, tr(q.message.chat.id, "main_menu_title"), _main_menu(q.message.chat.id))


@router.message(F.text & ~F.text.startswith("/"))
async def on_plain_text(m: Message):
    """Typing a country name anywhere is a search."""
    query = m.text.strip()[:40]
    if not query:
        return
    text, markup = await _search_view(m.chat.id, query)
    await m.answer(text, reply_markup=markup)


# ---------------------------------------------------------------------------
# global error handler: never let an exception vanish silently
# ---------------------------------------------------------------------------

@router.error()
async def on_error(event: ErrorEvent):
    log.exception("Unhandled error while processing update: %s", event.exception)
    upd = event.update
    try:
        if upd.callback_query:
            await upd.callback_query.answer("⚠️ Something went wrong, try again.", show_alert=False)
    except Exception:
        pass
    return True
