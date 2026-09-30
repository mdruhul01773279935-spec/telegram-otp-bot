"""
Offline end-to-end test: real aiogram Dispatcher + handlers, but a FAKE
Telegram server and a FAKE SMS source.  No token / network needed.

    python test_flow.py
"""
import asyncio
import itertools
import os
import sys
import tempfile
import time

tmp = tempfile.mkdtemp()
os.environ.update(POLL_INTERVAL="1", LANGS_FILE=f"{tmp}/langs.json", HISTORY_FILE=f"{tmp}/h.jsonl")

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import TelegramMethod
from aiogram.types import CallbackQuery, Chat, Message, Update, User

import handlers
import traffic
import scrapers
from scrapers import BaseSource, SmsMessage
from lang import STRINGS

CHAT, USER = 4242, User(id=4242, is_bot=False, first_name="T")
ids = itertools.count(100)


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []          # (method_name, data)

    async def close(self): ...
    async def stream_content(self, *a, **k): yield b""

    async def make_request(self, bot, method: TelegramMethod, timeout=None):
        data = method.model_dump(exclude_none=True)
        if getattr(method, "reply_markup", None) is not None:
            data["reply_markup"] = method.reply_markup        # keep real objects
        self.calls.append((type(method).__name__, data))
        name = type(method).__name__
        if name in ("SendMessage", "EditMessageText"):
            mid = data.get("message_id") or next(ids)
            return Message(message_id=mid, date=int(time.time()),
                           chat=Chat(id=CHAT, type="private"), text=data.get("text", ""))
        return True

    def of(self, name):
        return [d for n, d in self.calls if n == name]


class Fake(BaseSource):
    name = "fake.test"
    def __init__(self):
        self.inbox: list[SmsMessage] = [SmsMessage("OLD", "1 year ago", "old message")]
        self.tick = 0
    async def list_countries(self):
        return {"Very Long Country Name " * 2 + "é": "slug", "Sweden": "sweden"}
    async def list_numbers(self, key):
        return ["46731299509", "447520635797", "8801712345678"]
    async def get_messages(self, number, key=None):
        self.tick += 1
        # relative times change on EVERY request, like the real sites
        return [SmsMessage(m.sender, m.time if m.sender == "OLD" else f"{self.tick} minutes ago", m.text)
                for m in self.inbox]


fake = Fake()
scrapers.SOURCES[:] = [fake]
handlers.SOURCES[:] = [fake]

session = FakeSession()
bot = Bot("123:ABC", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()
dp.include_router(handlers.router)
upd_id = itertools.count(1)
msg_ids = itertools.count(1000)
fails = 0


def check(cond, label):
    global fails
    print(("✅ " if cond else "❌ ") + label)
    if not cond:
        fails += 1


async def send_text(text):
    m = Message(message_id=next(msg_ids), date=int(time.time()), chat=Chat(id=CHAT, type="private"),
                from_user=USER, text=text,
                entities=[{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}])
    await dp.feed_update(bot, Update(update_id=next(upd_id), message=m))


async def press(data, msg_id=None, text="menu"):
    m = Message(message_id=msg_id or next(msg_ids), date=int(time.time()),
                chat=Chat(id=CHAT, type="private"), from_user=bot and User(id=1, is_bot=True, first_name="B"), text=text)
    cq = CallbackQuery(id=str(next(upd_id)), from_user=USER, chat_instance="x", data=data, message=m)
    await dp.feed_update(bot, Update(update_id=next(upd_id), callback_query=cq))


def buttons(call_data):
    mk = call_data.get("reply_markup")
    return [b for row in (mk.inline_keyboard if mk else []) for b in row]


def last_markup_buttons():
    for n, d in reversed(session.calls):
        if n in ("EditMessageText", "SendMessage") and d.get("reply_markup"):
            return d["reply_markup"].inline_keyboard
    return []


async def main():
    bot._me = User(id=1, is_bot=True, first_name="B", username="b")
    # ---- basic commands
    await send_text("/start")
    check(session.of("SendMessage"), "/start answered")
    await send_text("/history")
    await send_text("/ping")
    await send_text("/lang")

    # ---- menu flow via buttons
    await press("src:-1")
    await press("src:0")
    rows = last_markup_buttons()
    flat = [b for r in rows for b in r]
    check(len(rows) >= 3 and any(len(r) == 1 for r in rows), "countries keyboard built")
    check(all(len(b.callback_data.encode()) <= 64 for b in flat), "every country callback_data <= 64 bytes")
    ctr = next(b for b in flat if b.callback_data.startswith("ctr:") and "Sweden" in b.text)
    await press(ctr.callback_data)
    rows = last_markup_buttons()
    flat = [b for r in rows for b in r]
    check(any(b.text == "+8801 712345678" or b.text.startswith("+880") for b in flat), "number buttons shown")
    check(any(b.text == "1/1" for b in flat) and any(b.callback_data == "live:sort" for b in flat),
          "numbers keyboard: nav row + live-activity button")
    check(flat[-1].callback_data == "src:0", "back button returns to the SOURCE countries (not auto)")

    # ---- Auto mode
    await press("auto:go")
    auto = [b for r in last_markup_buttons() for b in r]
    actr = next(b for b in auto if b.callback_data.startswith("actr:"))
    await press(actr.callback_data)
    flat = [b for r in last_markup_buttons() for b in r]
    check(flat[-1].callback_data == "auto:go", "auto mode back -> auto list")
    # go back to specific source list for the watch
    await press(ctr.callback_data)

    # ---- live activity sort on the number list
    await press("live:sort")
    flat = [b for r in last_markup_buttons() for b in r]
    nb = [b for b in flat if b.callback_data.startswith("num:")]
    check(nb and all(b.text[0] in "🟢🟡🔴⚪" for b in nb), "number buttons now carry 🟢/🟡/🔴 activity badges")
    check(flat[-1].callback_data == "src:0", "back button still correct after sort")
    check("Sorted by live activity" in session.of("EditMessageText")[-1]["text"], "sorted note in title")

    # ---- live traffic screen
    fake.inbox.insert(0, SmsMessage("PayPal", "now", "PP-111 is your code"))
    traffic._cache.clear()                                  # (feed tolerates <=20 s old data)
    await press("live:go")
    live_txt = session.of("EditMessageText")[-1]["text"]
    flat = [b for r in last_markup_buttons() for b in r]
    check("Live traffic" in live_txt and "OLD" not in live_txt, "live traffic feed shown (old msgs excluded)")
    check("PayPal" in live_txt and "PP-111" in live_txt, "fresh SMS is in the live feed")
    check(any(b.callback_data.startswith("num:") for b in flat) and any(b.callback_data == "live:go" for b in flat),
          "live feed has pick-number + refresh buttons")
    await send_text("/live")
    check("Live traffic" in session.of("SendMessage")[-1]["text"], "/live command")
    fake.inbox[:] = [m for m in fake.inbox if m.sender != "PayPal"]

    # ---- country search
    await send_text("swe")
    flat = [b for r in last_markup_buttons() for b in r]
    check(any("Sweden" in b.text and b.callback_data.startswith("actr:") for b in flat), "typing 'swe' finds Sweden")
    await send_text("/country swedn")                       # typo
    flat = [b for r in last_markup_buttons() for b in r]
    check(any("Sweden" in b.text for b in flat), "/country with a typo still finds Sweden")
    await send_text("/country zzzzqqq")
    check("No country matches" in session.of("SendMessage")[-1]["text"], "no-match message")
    check(handlers._match_countries("usa", ["United States", "Austria"]) == ["United States"], "alias usa -> United States")
    check(handlers._match_countries("uk", ["United Kingdom", "Ukraine"])[0] == "United Kingdom", "alias uk")
    await send_text("/country")
    check("Type a country name" in session.of("SendMessage")[-1]["text"], "/country without args prompts")
    # pressing a search result opens the numbers
    flat = [b for r in last_markup_buttons() for b in r]
    await send_text("sweden")
    res = next(b for r in last_markup_buttons() for b in r if b.callback_data.startswith("actr:"))
    await press(res.callback_data)
    check(any(b.callback_data.startswith("num:") for r in last_markup_buttons() for b in r), "search result -> numbers")

    # ---- Auto list pagination (was capped at 95 countries)
    handlers._auto_merged[CHAT] = {f"Country {i:03d}": 1 for i in range(230)}
    handlers._auto_merged[CHAT]["United States"] = 2
    mk = handlers._auto_keyboard(CHAT, 0).inline_keyboard
    allb = [b for r in mk for b in r]
    check(len(allb) <= 100 and all(len(b.callback_data.encode()) <= 64 for b in allb), "auto page 0 <=100 buttons, valid callback_data")
    check(any(b.callback_data == "apg:1" for b in allb) and any(b.text.startswith("⭐") for b in allb), "auto list: next page + popular row")
    last = [b for r in handlers._auto_keyboard(CHAT, 19).inline_keyboard for b in r]
    check(any(b.callback_data == "apg:18" for b in last) and not any(b.callback_data == "apg:20" for b in last), "auto last page nav")
    await press("apg:2")
    check(True, "apg callback handled")

    # ---- temp-number country labels (offline regression)
    from scrapers import TempNumberSource
    src = TempNumberSource()
    html = "".join(f'<a href="https://temp-number.com/countries/{slug}">{label}</a>' for slug, label in [
        ("france", "France +33"), ("egypt", "Egypt 20"), ("canada", "Trending Canada +1 599 numbers"),
        ("australia", "Australia +61 1 number"), ("cambodia", "Cambodia 855 4 numbers"),
        ("canada", "Canada"), ("empty", "Nowhere +999 0 numbers")])
    async def fake_get(url, **kw): return html
    src._get_text = fake_get
    got = await src.list_countries()
    check(got == {"France": "france", "Egypt": "egypt", "Canada": "canada",
                  "Australia": "australia", "Cambodia": "cambodia"}, f"temp-number label cleaning {got}")

    # ---- new sources: offline parser tests on captured markup
    from scrapers import ReceiveSmsCoSource, SmssNetSource, canon
    rs = ReceiveSmsCoSource()
    pages = {
        rs.countries_url: '<a href="/us-phone-numbers/us/">United States Active numbers: 131</a>'
                          '<a href="/dutch-phone-numbers/nl/">Netherlands Active numbers: 1</a>'
                          '<a href="/free-phone-numbers">x</a>',
        "https://www.receivesms.co/us-phone-numbers/us/":
            '<a href="/us-phone-number/22646/">+1 475-231-8208 3 days ago</a>'
            '<a href="/us-phone-number/22682/">+1 502-358-9061 6 hours ago</a>',
        "https://www.receivesms.co/us-phone-numbers/US/2/":
            '<a href="/us-phone-number/22680/">+1 213-914-3168 just now</a>',
        "https://www.receivesms.co/us-phone-numbers/US/3/": "<html></html>",
        "https://www.receivesms.co/us-phone-number/22646/":
            '<article class="entry-card"><div class="entry-head"><a class="from-link">22395</a>'
            '<div class="entry-right"><span class="chip">Code: <strong>9983</strong></span><span class="muted">4 minutes ago</span></div></div>'
            '<div class="entry-body"><div class="sms">Your TangoMe code is: 9983</div></div></article>',
    }
    async def rs_get(url, **kw): return pages[url]
    rs._get_text = rs_get
    rc = await rs.list_countries()
    check(rc == {"United States": "us-phone-numbers/us", "Netherlands": "dutch-phone-numbers/nl"} and rs.counts["United States"] == 131,
          f"receivesms.co countries+counts {rc}")
    rn = await rs.list_numbers("us-phone-numbers/us")
    check(rn == ["14752318208", "15023589061", "12139143168"], f"receivesms.co numbers follow pagination {rn}")
    check(rs.age_hint["15023589061"] == "6 hours ago", "receivesms.co age hint captured")
    rm = await rs.get_messages("14752318208", "us-phone-numbers/us")
    check(len(rm) == 1 and rm[0].sender == "22395" and rm[0].time == "4 minutes ago" and "9983" in rm[0].text, "receivesms.co inbox parsed")

    sm = SmssNetSource()
    spages = {
        sm.home + "/countries": '<a href="/countries/united-kingdom">United Kingdom 10 number s · 10 online →</a>'
                                '<a href="/countries/austria">Austria 1 number · 1 online →</a><a href="/countries">All</a>',
        sm.home + "/countries/united-kingdom": '<a href="/number/447487588932">+447487588932 Online</a>',
        sm.home + "/number/447487588932":
            '<div class="divide-y divide-border"><div class="p-4"><div><span class="shrink-0 grid">N</span>'
            '<span class="truncate font-semibold">NetTV</span><span class="shrink-0 text-xs"></span></div>'
            '<p class="mt-3 whitespace-pre-line">WhatsApp code 401-572</p></div></div>',
    }
    async def sm_get(url, **kw): return spages[url]
    sm._get_text = sm_get
    check(await sm.list_countries() == {"United Kingdom": "united-kingdom", "Austria": "austria"} and sm.counts["United Kingdom"] == 10, "smss.net countries+counts")
    check(await sm.list_numbers("united-kingdom") == ["447487588932"], "smss.net numbers")
    mm = await sm.get_messages("447487588932")
    check(len(mm) == 1 and mm[0].sender == "NetTV" and mm[0].time == "" and "401-572" in mm[0].text, f"smss.net inbox parsed {mm}")
    check(canon("Czechia") == canon("Czech") == "Czech Republic" and canon("USA") == "United States", "country names canonicalised across sources")
    check(handlers._fmt_count(1234) == "1.2k" and handlers._fmt_count(12) == "12" and handlers._fmt_count(2000) == "2k", "count formatting")

    # temp-number: empty countries are hidden only when positively verified empty
    tn = TempNumberSource(); tn._dead = {"france"}
    async def tn_get(url, **kw): return ('<a href="https://temp-number.com/countries/france">France +33</a>'
                                         '<a href="https://temp-number.com/countries/canada">Canada +1 5 numbers</a>')
    tn._get_text = tn_get
    check(await tn.list_countries() == {"Canada": "canada"}, "verified-empty country hidden, others kept")

    # ---- age parser
    cases = {"Just now": 0, "57 seconds ago": 57, "2 minutes ago": 120, "5 hour ago": 18000, "a minute ago": 60,
             "1 year ago": 31536000, "3 days ago": 259200, "": None, "whatever": None}
    bad = {k: traffic.parse_age(k) for k, v in cases.items() if traffic.parse_age(k) != v}
    check(not bad, f"parse_age cases {bad}")
    check(traffic.fmt_age(45) == "now" and traffic.fmt_age(300) == "5m" and traffic.fmt_age(7300) == "2h", "fmt_age")

    # ---- start watching
    await press(ctr.callback_data)                          # re-open the number list
    num = next(b for b in [b for r in last_markup_buttons() for b in r] if b.callback_data.startswith("num:"))
    status_id = 777
    await press(num.callback_data, msg_id=status_id)
    check(len(handlers.manager.by_user(CHAT)) == 1, "watcher started")
    await press(num.callback_data, msg_id=status_id)
    check(len(handlers.manager.by_user(CHAT)) == 1, "same number twice -> no duplicate watcher")

    before = len(session.of("SendMessage"))
    await asyncio.sleep(3.5)       # several polls with CHANGING relative times
    check(len(session.of("SendMessage")) == before, "old inbox NOT forwarded; no duplicates from changing 'x minutes ago'")

    fake.inbox.insert(0, SmsMessage("Google", "now", "G-123456 is your <#> code"))
    await asyncio.sleep(2.5)
    sms = [d for d in session.of("SendMessage") if "G-123456" in d["text"]]
    check(len(sms) == 1, f"new SMS forwarded exactly once (got {len(sms)})")
    check(sms and "&lt;#&gt;" in sms[0]["text"], "SMS text HTML-escaped")

    # same OTP text resent later must be forwarded again
    fake.inbox.insert(0, SmsMessage("Google", "now", "G-123456 is your <#> code"))
    await asyncio.sleep(2.5)
    sms = [d for d in session.of("SendMessage") if "G-123456" in d["text"]]
    check(len(sms) == 2, f"identical resent OTP forwarded again (got {len(sms)})")

    # ---- history with '<' in text must not crash
    n_err = len([1 for n, d in session.calls if n == "SendMessage" and "Can't parse" in d.get("text", "")])
    await send_text("/history")
    hist = session.of("SendMessage")[-1]["text"]
    check("&lt;#&gt;" in hist and "<#>" not in hist, "/history escapes HTML")

    # ---- stop/extend pressed on an SMS message must NOT overwrite the OTP
    wid = handlers.manager.by_user(CHAT)[0].wid
    edits_before = len(session.of("EditMessageText"))
    await press(f"ext:{wid}:s", msg_id=5555, text="OTP TEXT")
    await press(f"stop:{wid}:s", msg_id=5555, text="OTP TEXT")
    overwritten = [d for d in session.of("EditMessageText") if d.get("message_id") == 5555 and d.get("text")]
    check(not overwritten, "Stop/Extend on an SMS message never edits the SMS text")
    status_edits = [d for d in session.of("EditMessageText") if d.get("message_id") == status_id]
    check(status_edits, "status message updated instead")
    check(len(handlers.manager.by_user(CHAT)) == 0, "watcher stopped")
    await press(f"stop:{wid}", msg_id=status_id)       # stale button: must not crash
    check(True, "stale stop button handled")

    # ---- time up path
    handlers.manager  # restart a watcher with 2s
    await press(num.callback_data, msg_id=888)
    w = handlers.manager.by_user(CHAT)[0]
    w.seconds_left = 2
    await asyncio.sleep(4)
    check(len(handlers.manager.by_user(CHAT)) == 0, "watcher auto-ends on time up")
    check(any(d.get("message_id") == 888 and "👀" in d["text"] for d in session.of("EditMessageText")), "time-up status shown")

    # ---- limits & language
    await press(ctr.callback_data)                                   # re-open the number list
    nums = [b.callback_data for r in last_markup_buttons() for b in r if b.callback_data.startswith("num:")]
    for k, cd in enumerate(nums[:3]):
        await press(cd, msg_id=900 + k)
    check(len(handlers.manager.by_user(CHAT)) == 2, "MAX_ACTIVE_PER_USER limit enforced (2)")
    await handlers.manager.stop_user(CHAT)
    await press("lang:bn")
    from lang import get_lang
    check(get_lang(CHAT) == "bn", "language switch to Bengali")

    # ---- every string renders in both languages (format placeholders match)
    import string
    bad = []
    for k in STRINGS["en"]:
        fe = {f for _, f, _, _ in string.Formatter().parse(STRINGS["en"][k]) if f}
        fb = {f for _, f, _, _ in string.Formatter().parse(STRINGS["bn"][k]) if f}
        if fe != fb:
            bad.append(k)
    check(not bad, f"EN/BN placeholders identical {bad}")

    handlers.manager.stop_all()
    print("\nALL FLOW TESTS PASSED ✔" if not fails else f"\n{fails} FAILED ✘")
    sys.exit(1 if fails else 0)


asyncio.run(main())
