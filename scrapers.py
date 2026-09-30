"""
Free SMS sources: scrapers for websites that provide disposable public
phone numbers and their public inboxes.  No API keys, no payments.

Each source implements the same tiny interface:

    async def list_countries() -> dict[str, str]
        country display name -> lookup key (slug / id used in URLs)

    async def list_numbers(key: str) -> list[str]
        digit-only phone numbers available for that country

    async def get_messages(number: str, key: str | None = None) -> list[SmsMessage]

A source raises SourceError when the site is unreachable or the HTML
structure changed (scrapers break when sites redesign — see README).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

from config import HTTP_TIMEOUT, MAX_NUMBERS_PER_COUNTRY, MAX_PAGES, USER_AGENT, WARMUP_INTERVAL_MIN

log = logging.getLogger("scrapers")


class SourceError(Exception):
    """Raised when a source cannot be reached or parsed."""


@dataclass
class SmsMessage:
    sender: str = ""
    time: str = ""
    text: str = ""
    uid: str = ""          # site-provided unique id (if the site has one)

    @property
    def key(self) -> str:
        """Fingerprint used to deduplicate messages.

        The *time* is deliberately NOT part of the key: most sites show
        relative times ("5 minutes ago") which change on every request and
        would make the same SMS look new on every poll.
        """
        if self.uid:
            return f"id:{self.uid}"
        raw = f"{self.sender}|{self.text}"
        return re.sub(r"\s+", " ", raw).strip().lower()

    def pretty(self, lang: str = "en") -> str:
        from_lbl = "👤 From:" if lang != "bn" else "👤 পাঠিয়েছেন:"
        lines = []
        if self.sender:
            lines.append(f"{from_lbl} <b>{html_escape(self.sender)}</b>")
        if self.time:
            lines.append(f"🕒 {html_escape(self.time)}")
        lines.append("")
        lines.append(html_escape(self.text[:3000]))
        return "\n".join(lines)


def html_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

COUNTRY_BY_PREFIX: list[tuple[str, str]] = [
    ("880", "Bangladesh"), ("234", "Nigeria"), ("966", "Saudi Arabia"),
    ("971", "UAE"), ("380", "Ukraine"), ("972", "Israel"), ("358", "Finland"),
    ("353", "Ireland"), ("351", "Portugal"), ("420", "Czech Republic"),
    ("421", "Slovakia"), ("886", "Taiwan"), ("852", "Hong Kong"),
    ("82", "South Korea"), ("81", "Japan"), ("91", "India"), ("92", "Pakistan"),
    ("90", "Turkey"), ("62", "Indonesia"), ("63", "Philippines"),
    ("66", "Thailand"), ("84", "Vietnam"), ("94", "Sri Lanka"),
    ("65", "Singapore"), ("60", "Malaysia"), ("61", "Australia"),
    ("64", "New Zealand"), ("1", "United States"), ("44", "United Kingdom"),
    ("49", "Germany"), ("33", "France"), ("39", "Italy"), ("34", "Spain"),
    ("31", "Netherlands"), ("32", "Belgium"), ("48", "Poland"),
    ("46", "Sweden"), ("47", "Norway"), ("45", "Denmark"),
    ("43", "Austria"), ("41", "Switzerland"), ("40", "Romania"),
    ("36", "Hungary"), ("30", "Greece"), ("7", "Russia"),
    ("86", "China"), ("55", "Brazil"), ("52", "Mexico"),
    ("54", "Argentina"), ("57", "Colombia"), ("56", "Chile"),
    ("51", "Peru"), ("20", "Egypt"), ("98", "Iran"),
]


def country_for_number(digits: str) -> str:
    for prefix, name in COUNTRY_BY_PREFIX:
        if digits.startswith(prefix):
            return name
    return f"Unknown (+{digits[:3]})"


_CANON = {
    "usa": "United States", "us": "United States", "united states of america": "United States",
    "america": "United States", "uk": "United Kingdom", "great britain": "United Kingdom",
    "england": "United Kingdom", "czech": "Czech Republic", "czechia": "Czech Republic",
    "uae": "United Arab Emirates", "russian federation": "Russia", "holland": "Netherlands",
    "korea": "South Korea", "republic of korea": "South Korea", "burma": "Myanmar",
    "guinea-bissau": "Guinea-Bissau", "ivory coast": "Cote d'Ivoire", "hong kong sar": "Hong Kong",
    "viet nam": "Vietnam", "turkiye": "Turkey",
}


def canon(name: str) -> str:
    """Same country, same spelling across every source (so Auto mode can merge)."""
    n = re.sub(r"\s+", " ", name or "").strip()
    return _CANON.get(n.lower(), n)


def pretty_number(digits: str) -> str:
    """Display helper: 447520635797 -> +44 7520 635797 (never drops digits)."""
    digits = re.sub(r"\D", "", str(digits))
    if not digits:
        return ""
    cc = ""
    for prefix, _name in COUNTRY_BY_PREFIX:
        if digits.startswith(prefix) and len(digits) > len(prefix) + 4:
            cc = prefix
            break
    rest = digits[len(cc):]
    if cc == "1" and len(rest) == 10:                  # NANP: +1 201 857 7757
        groups = [rest[:3], rest[3:6], rest[6:]]
    elif len(rest) <= 4:
        groups = [rest]
    else:                                              # +44 7520 635797
        groups = [rest[:4], rest[4:]]
        if len(groups[1]) > 7:
            groups = [rest[:4], rest[4:8], rest[8:]]
    return "+" + " ".join(([cc] if cc else []) + groups)


class BaseSource:
    name: str = "base"
    home: str = ""
    _client: httpx.AsyncClient | None = None
    counts: dict[str, int] = {}          # default; every real source gets its own in __init__

    def __init__(self) -> None:
        # country display name -> how many numbers the site advertises (if known)
        self.counts: dict[str, int] = {}

    async def warm_up(self) -> None:
        """Optional background job (e.g. hide countries that have no numbers)."""

    async def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept-Language": "en-US,en;q=0.9",
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                },
            )
        return self._client

    _sem: asyncio.Semaphore | None = None
    MAX_CONCURRENT = 4          # be polite: at most N simultaneous requests per site

    async def _get_text(self, url: str, **kw) -> str:
        c = await self.client()
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.MAX_CONCURRENT)
        last: Exception | None = None
        for attempt in range(3):                      # retries: transient errors + 429
            try:
                async with self._sem:
                    r = await c.get(url, **kw)
                if r.status_code == 429:              # rate limited -> back off, then retry
                    wait = 2.0 * (attempt + 1)
                    ra = r.headers.get("retry-after", "")
                    if ra.isdigit():
                        wait = min(float(ra), 20.0)
                    last = httpx.HTTPStatusError("429 Too Many Requests", request=r.request, response=r)
                    await asyncio.sleep(wait)
                    continue
                r.raise_for_status()
                return r.text
            except httpx.HTTPError as e:
                last = e
                if attempt < 2:
                    await asyncio.sleep(1)
        raise SourceError(f"{self.name}: request failed: {last!r}") from last

    async def list_countries(self) -> dict[str, str]:
        raise NotImplementedError

    async def list_numbers(self, key: str) -> list[str]:
        raise NotImplementedError

    async def get_messages(self, number: str, key: str | None = None) -> list[SmsMessage]:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# 1. temp-number.com  (many countries, full message text, sender masked)
# ---------------------------------------------------------------------------

class TempNumberSource(BaseSource):
    name = "temp-number.com"
    home = "https://temp-number.com"
    countries_url = home + "/countries"
    numbers_url = home + "/countries/{slug}"
    inbox_url = home + "/temporary-numbers/{slug}/{number}"

    _label_re = re.compile(
        r"^(?:Trending\s+)?(?P<name>.+?)\s+\+?\d[\d\s]*?\s(?P<count>\d+)\s+numbers?$", re.I
    )
    MAX_CONCURRENT = 3
    _dead: set[str] = set()               # slugs positively verified to list 0 numbers

    async def list_countries(self) -> dict[str, str]:
        """display name -> slug.  Countries with 0 numbers are skipped."""
        soup = BeautifulSoup(await self._get_text(self.countries_url), "html.parser")
        out: dict[str, str] = {}
        seen_slugs: set[str] = set()
        counts: dict[str, int] = {}
        for a in soup.select('a[href*="/countries/"]'):
            href = a.get("href", "")
            slug = href.rstrip("/").rsplit("/", 1)[-1]
            if not slug or slug == "countries" or slug in seen_slugs:
                continue
            label = a.get_text(" ", strip=True)
            m = self._label_re.match(label)
            known = bool(m)
            if m:
                name, count = m.group("name"), int(m.group("count"))
            else:                                       # "France +33" / "Egypt 20" (no count shown)
                name = re.sub(r"^Trending\s+", "", label)
                name = re.sub(r"\s+\+?\d{1,4}$", "", name)
                count = 1
            name = canon(re.sub(r"\(.*?\)", "", name).strip())
            if not name:
                name = canon(slug.replace("-", " ").title())
            seen_slugs.add(slug)
            if count > 0 and name not in out:
                out[name] = slug
                if known:
                    counts[name] = count
        self.counts = counts
        if self._dead:                                  # hide countries the warm-up found empty
            alive = {n: sl for n, sl in out.items() if sl not in self._dead}
            if alive:
                self.counts = {n: c for n, c in counts.items() if n in alive}
                return alive
        return out

    def _page_url(self, slug: str, page: int) -> str:
        base = self.numbers_url.format(slug=slug)
        return base if page <= 1 else f"{base}/{page}"

    @staticmethod
    def _number_links(soup: BeautifulSoup, slug: str) -> list[str]:
        nums: list[str] = []
        for a in soup.select(f'a[href*="/temporary-numbers/{slug}/"]'):
            m = re.search(r"/(\d{6,15})$", a["href"].rstrip("/"))
            if m and m.group(1) not in nums:
                nums.append(m.group(1))
        return nums

    async def list_numbers(self, slug: str) -> list[str]:
        """Follow the site's pagination (20 numbers per page)."""
        first = BeautifulSoup(await self._get_text(self._page_url(slug, 1)), "html.parser")
        nums = self._number_links(first, slug)
        has_next = first.select_one('link[rel="next"], a[rel="next"]') is not None
        page = 2
        # sequential + short pause: fetching pages in parallel gets us HTTP 429
        while has_next and nums and page <= MAX_PAGES and len(nums) < MAX_NUMBERS_PER_COUNTRY:
            await asyncio.sleep(0.3)
            try:
                soup = BeautifulSoup(await self._get_text(self._page_url(slug, page)), "html.parser")
            except SourceError:
                break                                   # keep what we already have
            new = [n for n in self._number_links(soup, slug) if n not in nums]
            if not new:
                break
            nums += new
            has_next = soup.select_one('link[rel="next"], a[rel="next"]') is not None
            page += 1
        return nums[:MAX_NUMBERS_PER_COUNTRY]

    async def warm_up(self) -> None:
        """Find out which of the ~230 listed countries really show numbers.

        Gentle on purpose (2 workers + small pause): the site rate-limits.
        A country is only hidden when its page was fetched successfully and
        contained 0 numbers; errors never hide anything.
        """
        countries = await self.list_countries()
        todo: asyncio.Queue = asyncio.Queue()
        for sl in countries.values():
            todo.put_nowait(sl)
        dead: set[str] = set()
        checked = 0

        async def worker() -> None:
            nonlocal checked
            while True:
                try:
                    slug = todo.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    soup = BeautifulSoup(await self._get_text(self._page_url(slug, 1)), "html.parser")
                except SourceError:
                    continue                                   # unknown -> keep visible
                checked += 1
                if not self._number_links(soup, slug):
                    dead.add(slug)
                await asyncio.sleep(0.3)

        await asyncio.gather(worker(), worker())
        if checked >= len(countries) // 2:                    # enough data to trust
            self._dead = dead
            log.info("%s: hiding %d/%d empty countries", self.name, len(dead), len(countries))

    async def get_messages(self, number: str, key: str | None = None) -> list[SmsMessage]:
        if not key:
            return []
        soup = BeautifulSoup(
            await self._get_text(self.inbox_url.format(slug=key, number=number)),
            "html.parser",
        )
        out: list[SmsMessage] = []
        for card in soup.select("article.msg-card"):
            bdi = card.select_one(".msg-from bdi")
            sender = bdi.get_text(strip=True) if bdi else ""
            t = card.select_one(".msg-time")
            body = card.select_one(".msg-body")
            if body:
                out.append(
                    SmsMessage(
                        sender=sender,
                        time=t.get_text(strip=True) if t else "",
                        text=body.get_text(" ", strip=True),
                    )
                )
        return out


# ---------------------------------------------------------------------------
# 2. mytempsms.com  (China/UK/USA/France/Germany...; note: the site masks the
#    actual OTP digits inside messages with ****)
# ---------------------------------------------------------------------------

def _decode_yi_digits(text: str) -> str:
    """mytempsms.com hides phone digits behind Yi-script glyphs (U+A000 = 0,
    U+A001 = 1, ...) to stop scrapers.  Turn them back into plain digits."""
    out = []
    for ch in text:
        o = ord(ch)
        if 0xA000 <= o <= 0xA009:
            out.append(str(o - 0xA000))
        elif ch.isdigit():
            out.append(ch)
    return "".join(out)


class MyTempSmsSource(BaseSource):
    """DISABLED by default: the site masks EVERY verification code as ******,
    so it can never deliver a usable OTP.  Enable with ENABLE_MASKED_SOURCES=1."""
    name = "mytempsms.com"
    home = "https://mytempsms.com"
    homepage = home + "/"
    number_link_re = re.compile(r"/receive-sms-online/([a-z0-9-]+)-phone-number-(\d+)\.html")

    def __init__(self) -> None:
        super().__init__()
        # real phone number (digits) -> (slug, page id used in the inbox URL)
        self._pages: dict[str, tuple[str, str]] = {}

    async def _homepage(self) -> BeautifulSoup:
        return BeautifulSoup(await self._get_text(self.homepage), "html.parser")

    def _scan(self, soup: BeautifulSoup) -> dict[str, list[tuple[str, str]]]:
        """slug -> [(real_number, page_id)], also refreshes the id map."""
        found: dict[str, list[tuple[str, str]]] = {}
        for a in soup.select('a[href*="receive-sms-online/"]'):
            m = self.number_link_re.search(a.get("href", ""))
            if not m:
                continue
            slug, page_id = m.group(1), m.group(2)
            real = _decode_yi_digits(a.get_text(" ", strip=True))
            if len(real) < 7:                       # 'View messages' links etc.
                continue
            if all(pid != page_id for _n, pid in found.get(slug, [])):
                found.setdefault(slug, []).append((real, page_id))
                self._pages[real] = (slug, page_id)
        return found

    async def list_countries(self) -> dict[str, str]:
        found = self._scan(await self._homepage())
        return {_slug_to_country(slug): slug for slug in found}

    async def list_numbers(self, slug: str) -> list[str]:
        found = self._scan(await self._homepage())
        return [n for n, _pid in found.get(slug, [])][:MAX_NUMBERS_PER_COUNTRY]

    async def get_messages(self, number: str, key: str | None = None) -> list[SmsMessage]:
        page = self._pages.get(number)
        if page is None:                             # e.g. after a restart
            self._scan(await self._homepage())
            page = self._pages.get(number)
        if page is None:
            raise SourceError(f"{self.name}: number {number} is no longer listed")
        slug, page_id = page
        url = f"{self.home}/receive-sms-online/{slug}-phone-number-{page_id}.html"
        soup = BeautifulSoup(await self._get_text(url), "html.parser")
        out: list[SmsMessage] = []
        for art in soup.select("article.sms-item"):            # current layout
            body = art.select_one(".sms-message")
            if not body:
                continue
            name = art.select_one(".sms-sender-name")
            t = art.select_one("time.sms-time")
            text = body.get_text(" ", strip=True)
            if text:
                out.append(SmsMessage(
                    sender=name.get_text(" ", strip=True) if name else "",
                    time=t.get_text(" ", strip=True) if t else "",
                    text=text,
                ))
        if out:
            return out
        for tr in soup.select("table.table-striped tr"):       # old layout (fallback)
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            text = tds[1].get_text(" ", strip=True)
            if text:
                out.append(SmsMessage(
                    sender=tds[0].get_text(" ", strip=True),
                    time=tds[2].get_text(" ", strip=True) if len(tds) > 2 else "",
                    text=text,
                ))
        return out


def _slug_to_country(slug: str) -> str:
    overrides = {"uk": "United Kingdom", "usa": "United States", "us": "United States"}
    if slug in overrides:
        return overrides[slug]
    return slug.replace("-", " ").title()


# ---------------------------------------------------------------------------
# 3. sms-online.co  (a handful of countries, full message text)
# ---------------------------------------------------------------------------

class SmsOnlineSource(BaseSource):
    name = "sms-online.co"
    home = "https://sms-online.co"
    numbers_url = home + "/receive-free-sms"
    inbox_url = home + "/receive-free-sms/{number}"

    async def list_countries(self) -> dict[str, str]:
        soup = BeautifulSoup(await self._get_text(self.numbers_url), "html.parser")
        names: dict[str, str] = {}
        seen: set[str] = set()
        counts: dict[str, int] = {}
        for a in soup.select('a[href*="/receive-free-sms/"]'):
            m = re.search(r"/(\d{6,15})$", a["href"].rstrip("/"))
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                name = canon(country_for_number(m.group(1)))
                names.setdefault(name, name)  # key == display name for this source
                counts[name] = counts.get(name, 0) + 1
        self.counts = counts
        return names

    async def list_numbers(self, key: str) -> list[str]:
        # key is just the country name for this source
        soup = BeautifulSoup(await self._get_text(self.numbers_url), "html.parser")
        nums: list[str] = []
        for a in soup.select('a[href*="/receive-free-sms/"]'):
            m = re.search(r"/(\d{6,15})$", a["href"].rstrip("/"))
            if m and canon(country_for_number(m.group(1))) == key and m.group(1) not in nums:
                nums.append(m.group(1))
        return nums[:MAX_NUMBERS_PER_COUNTRY]

    async def get_messages(self, number: str, key: str | None = None) -> list[SmsMessage]:
        soup = BeautifulSoup(
            await self._get_text(self.inbox_url.format(number=number)), "html.parser"
        )
        out: list[SmsMessage] = []
        for item in soup.select("div.list-item"):
            title = item.select_one(".list-item-title")
            if not title:
                continue
            meta = item.select_one(".list-item-meta")
            content = item.select_one(".list-item-content")
            sender = title.get_text(" ", strip=True)
            t = meta.get_text(" ", strip=True) if meta else ""
            body = content.get_text(" ", strip=True) if content else ""
            if body:
                out.append(SmsMessage(sender=sender, time=t, text=body))
        return out


# ---------------------------------------------------------------------------
# 4. receive-sms-online.info  (many countries, JSON endpoint for messages)
# ---------------------------------------------------------------------------

class ReceiveSmsOnlineInfoSource(BaseSource):
    name = "receive-sms-online.info"
    home = "https://receive-sms-online.info"
    homepage = home + "/"
    messages_api = home + "/get_sms_register.php"

    async def _homepage(self) -> BeautifulSoup:
        return BeautifulSoup(await self._get_text(self.homepage), "html.parser")

    async def list_countries(self) -> dict[str, str]:
        soup = await self._homepage()
        out: dict[str, str] = {}
        seen: set[str] = set()
        counts: dict[str, int] = {}
        for a in soup.select("a[href]"):
            m = re.match(r"^(\d{6,15})-([A-Za-z ]+)$", a.get("href", ""))
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                key = m.group(2).strip()
                out.setdefault(canon(key), key)        # display name canonical, key = site's spelling
                counts[canon(key)] = counts.get(canon(key), 0) + 1
        self.counts = counts
        return out

    async def list_numbers(self, key: str) -> list[str]:
        soup = await self._homepage()
        nums: list[str] = []
        for a in soup.select("a[href]"):
            m = re.match(r"^(\d{6,15})-([A-Za-z ]+)$", a.get("href", ""))
            if m and m.group(2).strip() == key and m.group(1) not in nums:
                nums.append(m.group(1))
        return nums[:MAX_NUMBERS_PER_COUNTRY]

    async def get_messages(self, number: str, key: str | None = None) -> list[SmsMessage]:
        c = await self.client()
        try:
            r = await c.get(
                self.messages_api,
                params={"phone": number},
                headers={"X-Alt-Data": str(int(time.time()))},
            )
            r.raise_for_status()
            data = r.json()
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            raise SourceError(f"{self.name}: messages request failed: {e}") from e
        out: list[SmsMessage] = []
        if not isinstance(data, list):
            return out
        for item in data:
            if not isinstance(item, dict):
                continue
            # real field names used by the site's own JavaScript
            text = re.sub(r"<[^>]+>", " ", str(item.get("mesaj") or item.get("sms") or item.get("message") or ""))
            text = re.sub(r"\s+", " ", text).strip()
            if not text or "you need to" in text.lower() and "login" in text.lower():
                continue                                   # login-gated placeholder
            out.append(
                SmsMessage(
                    sender=str(item.get("telefon") or item.get("from") or ""),
                    time=str(item.get("data") or item.get("date") or ""),
                    text=text,
                    uid=str(item.get("mesaje_id") or ""),
                )
            )
        # the site returns newest first; keep that order (watcher handles it)
        return out


# ---------------------------------------------------------------------------
# 5. receivesms.co  (22 countries, full text, paginated, "last activity" per number)
# ---------------------------------------------------------------------------

class ReceiveSmsCoSource(BaseSource):
    name = "receivesms.co"
    home = "https://www.receivesms.co"
    countries_url = home + "/available-countries"
    _country_re = re.compile(r"^/([a-z-]+-phone-numbers)/([a-z]{2})/?$", re.I)
    _number_re = re.compile(r"^/([a-z-]*phone-number)/(\d+)/?$", re.I)

    def __init__(self) -> None:
        super().__init__()
        self._paths: dict[str, str] = {}        # real number digits -> inbox path
        self.age_hint: dict[str, str] = {}      # real number digits -> "3 days ago"

    async def list_countries(self) -> dict[str, str]:
        soup = BeautifulSoup(await self._get_text(self.countries_url), "html.parser")
        out: dict[str, str] = {}
        counts: dict[str, int] = {}
        for a in soup.select('a[href*="-phone-numbers/"]'):
            m = self._country_re.match(a.get("href", ""))
            if not m:
                continue
            label = a.get_text(" ", strip=True)
            mm = re.match(r"^(.*?)\s+Active numbers:\s*(\d+)", label)
            name = canon(mm.group(1) if mm else label)
            n = int(mm.group(2)) if mm else 1
            if n > 0 and name and name not in out:
                out[name] = f"{m.group(1)}/{m.group(2)}"      # e.g. "us-phone-numbers/us"
                counts[name] = n
        self.counts = counts
        return out

    def _page_url(self, key: str, page: int) -> str:
        slug, code = key.split("/")
        return f"{self.home}/{slug}/{code}/" if page <= 1 else f"{self.home}/{slug}/{code.upper()}/{page}/"

    def _scan_page(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        found: list[str] = []
        for a in soup.select('a[href*="phone-number/"]'):
            m = self._number_re.match(a.get("href", ""))
            if not m:
                continue
            text = a.get_text(" ", strip=True)
            mm = re.match(r"^(\+[\d\s\-().]+?)(?:\s+(\d+\s+\w+\s+ago|just now|now))?$", text, re.I)
            digits = re.sub(r"\D", "", mm.group(1) if mm else text)
            if len(digits) < 7:
                continue
            self._paths[digits] = f"/{m.group(1)}/{m.group(2)}/"
            if mm and mm.group(2):
                self.age_hint[digits] = mm.group(2)
            if digits not in found:
                found.append(digits)
        return found

    async def list_numbers(self, key: str) -> list[str]:
        nums: list[str] = []
        for page in range(1, MAX_PAGES + 1):
            try:
                html = await self._get_text(self._page_url(key, page))
            except SourceError:
                if page == 1:
                    raise
                break
            new = [n for n in self._scan_page(html) if n not in nums]
            if not new:
                break
            nums += new
            if len(nums) >= MAX_NUMBERS_PER_COUNTRY:
                break
        return nums[:MAX_NUMBERS_PER_COUNTRY]

    async def get_messages(self, number: str, key: str | None = None) -> list[SmsMessage]:
        path = self._paths.get(number)
        if path is None and key:                       # e.g. after a restart
            await self.list_numbers(key)
            path = self._paths.get(number)
        if path is None:
            raise SourceError(f"{self.name}: number {number} is no longer listed")
        soup = BeautifulSoup(await self._get_text(self.home + path), "html.parser")
        out: list[SmsMessage] = []
        for art in soup.select("article.entry-card"):
            body = art.select_one(".sms")
            if not body:
                continue
            frm = art.select_one(".from-link")
            t = art.select_one(".entry-right .muted")
            text = body.get_text(" ", strip=True)
            if text:
                out.append(SmsMessage(
                    sender=frm.get_text(" ", strip=True) if frm else "",
                    time=t.get_text(" ", strip=True) if t else "",
                    text=text,
                ))
        return out


# ---------------------------------------------------------------------------
# 6. smss.net  (16 countries, full text; the site shows no timestamps)
# ---------------------------------------------------------------------------

class SmssNetSource(BaseSource):
    name = "smss.net"
    home = "https://smss.net"

    async def list_countries(self) -> dict[str, str]:
        soup = BeautifulSoup(await self._get_text(self.home + "/countries"), "html.parser")
        out: dict[str, str] = {}
        counts: dict[str, int] = {}
        for a in soup.select('a[href^="/countries/"]'):
            slug = a["href"].rstrip("/").rsplit("/", 1)[-1]
            label = a.get_text(" ", strip=True)
            m = re.match(r"^(.*?)\s+(\d+)\s+number", label)
            if not slug or slug == "countries" or not m:
                continue
            name = canon(m.group(1))
            if int(m.group(2)) > 0 and name not in out:
                out[name] = slug
                counts[name] = int(m.group(2))
        self.counts = counts
        return out

    async def list_numbers(self, slug: str) -> list[str]:
        soup = BeautifulSoup(await self._get_text(f"{self.home}/countries/{slug}"), "html.parser")
        nums: list[str] = []
        for a in soup.select('a[href*="/number/"]'):
            m = re.search(r"/number/(\d{6,15})$", a["href"].rstrip("/"))
            if m and m.group(1) not in nums:
                nums.append(m.group(1))
        return nums[:MAX_NUMBERS_PER_COUNTRY]

    async def get_messages(self, number: str, key: str | None = None) -> list[SmsMessage]:
        soup = BeautifulSoup(await self._get_text(f"{self.home}/number/{number}"), "html.parser")
        out: list[SmsMessage] = []
        for item in soup.select("div.divide-y > div"):
            text_el = item.select_one("p.whitespace-pre-line")
            if not text_el:
                continue
            sender_el = item.select_one("span.truncate")
            time_el = item.select_one("span.text-xs")      # (the avatar span is also shrink-0)
            text = text_el.get_text(" ", strip=True)
            if text:
                out.append(SmsMessage(
                    sender=sender_el.get_text(" ", strip=True) if sender_el else "",
                    time=time_el.get_text(" ", strip=True) if time_el else "",
                    text=text,
                ))
        return out


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------

SOURCES: list[BaseSource] = [
    TempNumberSource(),
    ReceiveSmsCoSource(),
    SmssNetSource(),
    SmsOnlineSource(),
    ReceiveSmsOnlineInfoSource(),
]
if os.environ.get("ENABLE_MASKED_SOURCES") == "1":
    SOURCES.append(MyTempSmsSource())


async def warm_up_loop() -> None:
    """Runs forever in the background: refreshes per-source caches (e.g. hides
    empty countries).  Failures are logged and retried next round."""
    while True:
        for src in list(SOURCES):
            try:
                await src.warm_up()
            except Exception as e:                      # never kill the loop
                log.warning("warm-up of %s failed: %s", src.name, e)
        await asyncio.sleep(max(5, WARMUP_INTERVAL_MIN) * 60)


async def close_all() -> None:
    for s in SOURCES:
        if s._client is not None:
            await s._client.aclose()
