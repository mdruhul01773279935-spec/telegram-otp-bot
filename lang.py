"""
Lightweight i18n: English (default) + Bengali (বাংলা).

Per-user language choice is stored in langs.json so it survives restarts.
Use:  from lang import tr;  text = tr(chat_id, "key", **placeholders)
"""

from __future__ import annotations

import json
import os

LANGS_FILE = os.environ.get("LANGS_FILE", "langs.json")

STRINGS: dict[str, dict[str, str]] = {
    # ------------------------------------------------------------------ EN
    "en": {
        "start": (
            "👋 Welcome! I get you a <b>free temporary phone number</b> and forward "
            "the <b>OTP / verification SMS</b> that arrives on it — straight to this chat.\n\n"
            "Numbers come from free public SMS-receive websites — no payments, no API keys.\n\n"
            "<i>⚠️ Heads up: these numbers are public and shared — anyone could read the "
            "code. Use them only for low-risk signups (testing, throwaway accounts), "
            "never for banking or security-sensitive accounts.</i>\n\n"
            "👇 Choose an option:"
        ),
        "help": (
            "❓ <b>How it works</b>\n"
            "1️⃣ Press \"Get a free number\" and pick a source (or Auto).\n"
            "2️⃣ Pick a country, then tap one of the numbers.\n"
            "3️⃣ Use that number on the website/app that asks for a phone.\n"
            "4️⃣ The bot polls the public inbox every few seconds and sends you every "
            "new SMS that arrives — your OTP will pop up here.\n\n"
            "💡 <b>Tips</b>\n"
            "• Pick a number that was added recently — old numbers are heavily used.\n"
            "• Many services (Telegram, WhatsApp, Google, banks…) block virtual numbers. "
            "If no SMS arrives, try another number or another source.\n"
            "• Free numbers are public: use the code fast, before someone else does.\n"
            "• Commands: /live · /country &lt;name&gt; · /active · /stopall · /history · /help · /lang\n\n"
            "⚠️ Use only for accounts you own."
        ),
        "choose_source": (
            "📱 <b>Choose a source</b>\n\n"
            "These are free SMS-receive websites the bot scrapes. <b>Auto</b> merges "
            "them all and is usually the easiest.\n\n"
            "<i>Note: all sources show the full SMS text, but free public numbers are "
            "shared and busy — if nothing arrives, try another number.</i>"
        ),
        "countries_title": "🌍 <b>{source}</b> — {count} countries:",
        "auto_title": "🌍 <b>Choose a country</b> — {count} available across all sources:",
        "numbers_title": "📞 <b>{country}</b> — {count} free numbers (tap one to start watching):",
        "numbers_title_auto": "📞 <b>{country}</b> — {count} free numbers (tap one to start watching):",
        "no_countries_anywhere": (
            "😕 Couldn't load any countries right now. The free sites may be down — "
            "try again in a few minutes."
        ),
        "source_error": (
            "😕 Couldn't reach <b>{source}</b>: {error}\n\n"
            "Try another source, or Auto."
        ),
        "source_no_countries": "😕 No countries found on {source} right now.",
        "numbers_error": "😕 Couldn't load numbers from <b>{source}</b>: {error}",
        "no_numbers_country": "😕 No free numbers for <b>{country}</b> right now.",
        "country_not_found": "😕 Country not found. Try another.",
        "no_numbers_anywhere": "😕 No free numbers for that country right now. Try another country.",
        "menu_stale": "😕 This menu is stale — please pick again.",
        "limit_reached": (
            "⛔ You already have {limit} active watchers. "
            "Stop one first (/active, /stopall)."
        ),
        "watching": (
            "👀 <b>Watching {number}</b> ({source})\n\n"
            "Use this number on the website that asks for a phone, then wait — "
            "every new SMS will appear here as a separate message.\n"
            "I'll watch for up to {minutes} minutes."
        ),
        "new_sms": "📩 <b>New SMS on {number}</b> ({source})\n\n{body}",
        "stopped": "⏹ Stopped watching <b>{number}</b> ({source}).",
        "already_stopped": "Already stopped.",
        "extended": (
            "👀 <b>Watching {number}</b> ({source})\n\n"
            "⏱ Extended — I'll keep watching for ~{minutes} more minutes."
        ),
        "active_title": "🕓 <b>Active watchers ({count}/{limit})</b>",
        "active_none": "🕓 No active watchers. Get a number with 📱 <b>Get a free number</b>.",
        "active_line": "• {number} — {source} (~{minutes} min left)",
        "stopall_done": "⏹ Stopped {count} watcher(s).",
        "history_none": "📭 No OTP history yet.",
        "history_title": "📜 <b>Recent received messages</b>",
        "history_line": "• {ts} — {number} ({source}): <i>{sms}</i>",
        "stats_title": (
            "📊 <b>Stats</b>\n"
            "• Active watchers: {active}\n"
            "• Messages forwarded (all time): {messages}\n"
            "• Users seen: {users}"
        ),
        "not_authorized": "⛔ Not authorized.",
        "ping": "🏓 pong",
        "time_up": (
            "⏰ Time is up, I stopped watching this number. "
            "You can pick a new one anytime."
        ),
        "source_down": (
            "⚠️ The website stopped responding, so I stopped watching. "
            "It may be down or changed its layout — try again later or "
            "pick another number/source."
        ),
        "unexpected_error": "⚠️ Unexpected error while watching: {error}",
        "fetching_countries": "Fetching countries…",
        "fetching_numbers": "Fetching numbers…",
        "main_menu_title": "👋 What would you like to do?",
        "btn_live": "📈 Live traffic",
        "btn_search": "🔎 Search country",
        "btn_sort_live": "📈 Check live activity",
        "btn_refresh": "🔄 Refresh",
        "popular_hint": "⭐ popular",
        "live_fetching": "Checking live traffic…",
        "live_title": "📈 <b>Live traffic</b> — newest SMS on public numbers (last {minutes} min)",
        "live_legend": "🟢 ≤15 min · 🟡 ≤2 h · 🔴 older\nTap a number below to watch it.",
        "live_none": "😕 No fresh SMS seen right now. Try again in a minute, or pick a country.",
        "sorted_note": "\n\n📈 <i>Sorted by live activity: 🟢 fresh · 🟡 a while ago · 🔴 quiet · 💬 = SMS in last hour</i>",
        "search_prompt": "🔎 Type a country name (e.g. <i>sweden</i>, <i>uk</i>, <i>usa</i>, <i>canada</i>).",
        "search_none": "😕 No country matches “{query}”. Try another spelling or pick from the list.",
        "search_results": "🔎 Results for “{query}”:",
        "choose_lang": "🌐 <b>Choose language / ভাষা বেছে নিন:</b>",
        "lang_set": "✅ Language set to {lang}.",
        # buttons
        "btn_get_number": "📱 Get a free number",
        "btn_active": "🕓 Active watchers",
        "btn_stop_all": "⏹ Stop all",
        "btn_help": "❓ Help",
        "btn_lang": "🌐 Language / ভাষা",
        "btn_auto": "⚡ Auto — best available source",
        "btn_back": "⬅️ Back",
        "btn_back_sources": "⬅️ Back to sources",
        "btn_stop": "⏹ Stop watching",
        "btn_extend": "⏱ +10 min",
        "btn_new_number": "📱 New number",
        "btn_main_menu": "⬅️ Main menu",
        "lang_en": "English 🇬🇧",
        "lang_bn": "বাংলা 🇧🇩",
    },
    # ------------------------------------------------------------------ BN
    "bn": {
        "start": (
            "👋 স্বাগতম! আমি আপনাকে একটি <b>ফ্রি টেম্পোরারি ফোন নম্বর</b> দিই, আর সেই "
            "নম্বরে আসা <b>OTP / ভেরিফিকেশন SMS</b> সরাসরি এই চ্যাটে পাঠাই।\n\n"
            "নম্বরগুলো ফ্রি পাবলিক SMS-রিসিভ ওয়েবসাইট থেকে আসে — কোনো পেমেন্ট বা API কী লাগে না।\n\n"
            "<i>⚠️ মনে রাখবেন: এই নম্বরগুলো পাবলিক এবং শেয়ার করা — অন্য যেকেউও কোড দেখতে পারে। "
            "শুধুমাত্র কম-ঝুঁকিপূর্ণ কাজে (টেস্টিং, ডামি অ্যাকাউন্ট) ব্যবহার করুন; "
            "ব্যাংক বা গুরুত্বপূর্ণ অ্যাকাউন্টে কখনোই নয়।</i>\n\n"
            "👇 একটা অপশন বেছে নিন:"
        ),
        "help": (
            "❓ <b>যেভাবে কাজ করে</b>\n"
            "1️⃣ \"ফ্রি নম্বর নিন\" চাপুন এবং সোর্স (বা ⚡ অটো) বেছে নিন।\n"
            "2️⃣ দেশ বেছে নিয়ে একটি নম্বরে ট্যাপ করুন।\n"
            "3️⃣ যে ওয়েবসাইট/অ্যাপে ফোন নম্বর চাওয়া হচ্ছে সেখানে নম্বরটি দিন।\n"
            "4️⃣ বট প্রতি কয়েক সেকেন্ডে ইনবক্স চেক করে নতুন SMS (OTP) আপনার চ্যাটে পাঠাবে।\n\n"
            "💡 <b>টিপস</b>\n"
            "• নতুন যোগ হওয়া নম্বর বেছে নিন — পুরনো নম্বর বেশি ব্যবহৃত হয়।\n"
            "• টেলিগ্রাম, হোয়াটসঅ্যাপ, গুগল, ব্যাংক… অনেক সেবা ভার্চুয়াল নম্বর ব্লক করে। "
            "SMS না এলে অন্য নম্বর বা সোর্স ট্রাই করুন।\n"
            "• ফ্রি নম্বর পাবলিক — কোডটি দ্রুত ব্যবহার করুন, অন্য কেউ ব্যবহার করার আগেই।\n"
            "• কমান্ড: /live · /country &lt;নাম&gt; · /active · /stopall · /history · /help · /lang\n\n"
            "⚠️ শুধুমাত্র নিজের অ্যাকাউন্টের জন্য ব্যবহার করুন।"
        ),
        "choose_source": (
            "📱 <b>সোর্স বেছে নিন</b>\n\n"
            "এগুলো ফ্রি SMS-রিসিভ ওয়েবসাইট, যেগুলো থেকে বট নম্বর সংগ্রহ করে। "
            "<b>⚡ অটো</b> সবগুলো একসাথে মিশিয়ে দেয় — সাধারণত সবচেয়ে সহজ।\n\n"
            "<i>নোট: সব সোর্সেই পুরো SMS টেক্সট দেখা যায়, কিন্তু ফ্রি পাবলিক নম্বর সবার সাথে "
            "শেয়ার করা ও ব্যস্ত — কিছু না এলে অন্য নম্বর চেষ্টা করুন।</i>"
        ),
        "countries_title": "🌍 <b>{source}</b> — {count}টি দেশ:",
        "auto_title": "🌍 <b>দেশ বেছে নিন</b> — সব সোর্স মিলিয়ে {count}টি দেশ পাওয়া যাচ্ছে:",
        "numbers_title": "📞 <b>{country}</b> — {count}টি ফ্রি নম্বর (ওয়াচ শুরু করতে যেকোনো একটিতে ট্যাপ করুন):",
        "numbers_title_auto": "📞 <b>{country}</b> — {count}টি ফ্রি নম্বর (ওয়াচ শুরু করতে যেকোনো একটিতে ট্যাপ করুন):",
        "no_countries_anywhere": (
            "😕 এখন কোনো দেশ লোড করা গেল না। ফ্রি সাইটগুলো ডাউন থাকতে পারে — "
            "কয়েক মিনিট পর আবার চেষ্টা করুন।"
        ),
        "source_error": (
            "😕 <b>{source}</b> এ পৌঁছানো গেল না: {error}\n\n"
            "অন্য সোর্স বা ⚡ অটো ট্রাই করুন।"
        ),
        "source_no_countries": "😕 {source} এ এখন কোনো দেশ পাওয়া যায়নি।",
        "numbers_error": "😕 <b>{source}</b> থেকে নম্বর লোড করা গেল না: {error}",
        "no_numbers_country": "😕 <b>{country}</b> এর জন্য এখন ফ্রি নম্বর নেই।",
        "country_not_found": "😕 দেশটি পাওয়া যায়নি। অন্য একটি চেষ্টা করুন।",
        "no_numbers_anywhere": "😕 এই দেশের জন্য এখন ফ্রি নম্বর নেই। অন্য দেশ চেষ্টা করুন।",
        "menu_stale": "😕 মেনুটি পুরনো হয়ে গেছে — আবার বেছে নিন।",
        "limit_reached": (
            "⛔ আপনার ইতিমধ্যে {limit}টি চলমান ওয়াচার আছে। "
            "আগে একটি বন্ধ করুন (/active, /stopall)।"
        ),
        "watching": (
            "👀 <b>{number}</b> ({source}) ওয়াচ হচ্ছে\n\n"
            "যে ওয়েবসাইটে ফোন নম্বর চাওয়া হচ্ছে সেখানে এই নম্বরটি ব্যবহার করুন। "
            "প্রতি কয়েক সেকেন্ডে ইনবক্স চেক করে নতুন SMS এখানে পাঠাবো।\n"
            "প্রায় {minutes} মিনিট পর্যন্ত ওয়াচ করবো।"
        ),
        "new_sms": "📩 <b>{number}</b> ({source}) — নতুন SMS\n\n{body}",
        "stopped": "⏹ <b>{number}</b> ({source}) ওয়াচ বন্ধ করা হয়েছে।",
        "already_stopped": "আগেই বন্ধ করা হয়েছে।",
        "extended": (
            "👀 <b>{number}</b> ({source})\n\n"
            "⏱ বাড়ানো হলো — আরও প্রায় {minutes} মিনিট ওয়াচ চলবে।"
        ),
        "active_title": "🕓 <b>চলমান ওয়াচার ({count}/{limit})</b>",
        "active_none": "🕓 কোনো চলমান ওয়াচার নেই। 📱 <b>ফ্রি নম্বর নিন</b> দিয়ে শুরু করুন।",
        "active_line": "• {number} — {source} (~{minutes} মিনিট বাকি)",
        "stopall_done": "⏹ {count}টি ওয়াচার বন্ধ করা হয়েছে।",
        "history_none": "📭 এখনো কোনো OTP ইতিহাস নেই।",
        "history_title": "📜 <b>সম্প্রতি পাওয়া SMS</b>",
        "history_line": "• {ts} — {number} ({source}): <i>{sms}</i>",
        "stats_title": (
            "📊 <b>পরিসংখ্যান</b>\n"
            "• চলমান ওয়াচার: {active}\n"
            "• মোট ফরওয়ার্ড হওয়া SMS: {messages}\n"
            "• মোট ইউজার: {users}"
        ),
        "not_authorized": "⛔ অনুমতি নেই।",
        "ping": "🏓 pong",
        "time_up": (
            "⏰ সময় শেষ — এই নম্বরটি ওয়াচ করা বন্ধ করলাম। "
            "যেকোনো সময় নতুন নম্বর নিতে পারবেন।"
        ),
        "source_down": (
            "⚠️ ওয়েবসাইটটি সাড়া দেওয়া বন্ধ করেছে, তাই ওয়াচ বন্ধ করলাম। "
            "সাইটটি ডাউন বা লেআউট বদলেছে — পরে আবার চেষ্টা করুন বা অন্য নম্বর/সোর্স বেছে নিন।"
        ),
        "unexpected_error": "⚠️ ওয়াচ করার সময় অপ্রত্যাশিত ত্রুটি: {error}",
        "fetching_countries": "দেশ লোড হচ্ছে…",
        "fetching_numbers": "নম্বর লোড হচ্ছে…",
        "main_menu_title": "👋 কী করতে চান?",
        "btn_live": "📈 লাইভ ট্রাফিক",
        "btn_search": "🔎 দেশ খুঁজুন",
        "btn_sort_live": "📈 লাইভ অ্যাক্টিভিটি দেখুন",
        "btn_refresh": "🔄 রিফ্রেশ",
        "popular_hint": "⭐ জনপ্রিয়",
        "live_fetching": "লাইভ ট্রাফিক দেখা হচ্ছে…",
        "live_title": "📈 <b>লাইভ ট্রাফিক</b> — পাবলিক নম্বরে সর্বশেষ SMS (গত {minutes} মিনিট)",
        "live_legend": "🟢 ≤১৫ মিনিট · 🟡 ≤২ ঘণ্টা · 🔴 পুরনো\nওয়াচ করতে নিচের যেকোনো নম্বরে ট্যাপ করুন।",
        "live_none": "😕 এই মুহূর্তে নতুন কোনো SMS দেখা যাচ্ছে না। এক মিনিট পর আবার চেষ্টা করুন, অথবা দেশ বেছে নিন।",
        "sorted_note": "\n\n📈 <i>লাইভ অ্যাক্টিভিটি অনুযায়ী সাজানো: 🟢 তাজা · 🟡 কিছুক্ষণ আগে · 🔴 নীরব · 💬 = গত ঘণ্টার SMS</i>",
        "search_prompt": "🔎 দেশের নাম লিখুন (যেমন <i>sweden</i>, <i>uk</i>, <i>usa</i>, <i>canada</i>)।",
        "search_none": "😕 “{query}” নামে কোনো দেশ পাওয়া যায়নি। অন্য বানানে চেষ্টা করুন বা তালিকা থেকে বেছে নিন।",
        "search_results": "🔎 “{query}” এর ফলাফল:",
        "choose_lang": "🌐 <b>ভাষা বেছে নিন / Choose language:</b>",
        "lang_set": "✅ ভাষা সেট করা হলো: {lang}।",
        # buttons
        "btn_get_number": "📱 ফ্রি নম্বর নিন",
        "btn_active": "🕓 চলমান ওয়াচার",
        "btn_stop_all": "⏹ সব বন্ধ করুন",
        "btn_help": "❓ সাহায্য",
        "btn_lang": "🌐 ভাষা / Language",
        "btn_auto": "⚡ অটো — সেরা সোর্স",
        "btn_back": "⬅️ ফিরে যান",
        "btn_back_sources": "⬅️ সোর্সে ফিরুন",
        "btn_stop": "⏹ ওয়াচ বন্ধ করুন",
        "btn_extend": "⏱ +১০ মিনিট",
        "btn_new_number": "📱 নতুন নম্বর",
        "btn_main_menu": "⬅️ মূল মেনু",
        "lang_en": "English 🇬🇧",
        "lang_bn": "বাংলা 🇧🇩",
    },
}

DEFAULT_LANG = "en"
SUPPORTED = ("en", "bn")

_langs: dict[int, str] = {}
_loaded = False


def _load() -> None:
    global _langs, _loaded
    if _loaded:
        return
    _loaded = True
    if os.path.exists(LANGS_FILE):
        try:
            with open(LANGS_FILE, encoding="utf-8") as f:
                data = json.load(f)
            _langs = {int(k): v for k, v in data.items() if v in SUPPORTED}
        except Exception:
            _langs = {}


def get_lang(chat_id: int) -> str:
    _load()
    return _langs.get(chat_id, DEFAULT_LANG)


def set_lang(chat_id: int, lang: str) -> str:
    _load()
    if lang not in SUPPORTED:
        lang = DEFAULT_LANG
    _langs[chat_id] = lang
    try:
        with open(LANGS_FILE, "w", encoding="utf-8") as f:
            json.dump({str(k): v for k, v in _langs.items()}, f, ensure_ascii=False)
    except OSError:
        pass
    return lang


def tr(chat_id: int, key: str, **kw) -> str:
    table = STRINGS.get(get_lang(chat_id), STRINGS[DEFAULT_LANG])
    template = table.get(key) or STRINGS[DEFAULT_LANG].get(key) or key
    try:
        return template.format(**kw) if kw else template
    except (KeyError, IndexError):
        return template
