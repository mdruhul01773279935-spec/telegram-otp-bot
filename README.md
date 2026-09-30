# 📱 Free OTP Telegram Bot

A Telegram bot that gives you a **free temporary phone number** and forwards the
**OTP / verification SMS** that arrives on it — straight to your chat.

**100% free** — no paid SMS services (no 5sim, no SMS-Activate), no API keys,
no credits. The bot reads disposable numbers from free public SMS-receive
websites and polls their public inboxes for you.

**🌐 Languages: English 🇬🇧 + Bengali (বাংলা) 🇧🇩** — switch anytime with
`/lang` or the 🌐 button in the main menu.

---

## ⚠️ Honest warnings (please read)

- **Numbers are public and shared.** Anyone can open the same inbox and read the
  same SMS. Use the code fast, and only for low-risk signups (throwaway
  accounts, testing, privacy). **Never** use these numbers for banking,
  government IDs, or security-sensitive accounts.
- **Many services block virtual numbers.** Telegram, WhatsApp, Google, Facebook,
  Instagram, banks… frequently refuse SMS delivery to these numbers. If nothing
  arrives in ~2 minutes, try another number or another source.
- **Use only for accounts you own.** This bot is for privacy and testing —
  not for bypassing verification on accounts that aren't yours.
- **Free sites change.** These are scraped websites; if one breaks, the bot
  reports it and you can still use the others. Run `python test_scrapers.py`
  anytime to check which sources are alive.

---

## 🚀 Quick start

### 1. Create the bot

1. Open Telegram → talk to [@BotFather](https://t.me/BotFather)
2. `/newbot` → choose a name and username → copy the **token** (looks like
   `123456789:AAH...`)

### 2. Install & run

```bash
cd telegram-otp-bot
pip install -r requirements.txt

# put your token in (either way works):
export BOT_TOKEN="123456789:AAH..."     # option A: env var
# or copy .env.example to .env and edit   # option B: .env file (auto-loaded)

python bot.py
```

That's it — the bot is online. Open your bot in Telegram and press **Start**.

> 💡 Optional: get your numeric user id from @userinfobot and set
> `ADMIN_IDS=123456789` (env) to unlock `/stats`.

### 🆕 Live traffic & country search

- **📈 Live traffic** (`/live`) – samples numbers across all sources and shows the
  freshest SMS from the last hour (sender, number, country, age). Tap a number to
  watch it. *Refresh* re-checks (data is at most ~20 s old).
- **📈 Check live activity** (button under any number list) – probes the numbers on
  screen and sorts them: 🟢 SMS in the last 15 min · 🟡 within 2 h · 🔴 quiet,
  plus `💬` = SMS received in the last hour. Pick a 🟢 number for best odds.
- **⭐ Popular + 🔎 search + paging** in Auto mode – the country list is paginated
  (it used to cut off at 95), shows popular countries first, and you can simply
  **type a country name** (`swe`, `usa`, `germny`…) or use `/country sweden`.

### 3. Use it

1. Press **📱 Get a free number** (or `/start`)
2. Choose **⚡ Auto** (recommended) or a specific source website
3. Pick a country, then tap a number
4. Use that number on the site/app that asks for a phone
5. The bot polls the inbox every ~8 s and sends every **new SMS** to your chat —
   your OTP appears as a message like:

```
📩 New SMS on +44 7520 635797 (sms-online.co)

👤 From: Coinbase
🕒 5 minutes ago

Your verification code is 481520. Do not share it.
```

Buttons on every message: **⏹ Stop watching** · **⏱ +10 min**

### 🌐 Language / ভাষা

The bot speaks **English** and **Bengali (বাংলা)**. Switch anytime:
`/lang` command, or the 🌐 button in the main menu. Your choice is saved and
survives restarts (`langs.json`).

বটটি **ইংরেজি** এবং **বাংলা** — দুটি ভাষায় কথা বলে। `/lang` কমান্ড বা মূল
মেনুর 🌐 বাটন দিয়ে যেকোনো সময় ভাষা বদলাতে পারেন।

---

## 📚 Commands

| Command     | What it does                                            |
|-------------|---------------------------------------------------------|
| `/start`    | Main menu                                                |
| `/active`   | List your active watchers + stop buttons                 |
| `/stopall`  | Stop all watchers                                        |
| `/history`  | Last 10 SMS you received (logged in `otp_history.jsonl`) |
| `/lang`     | Switch language: English 🇬🇧 / বাংলা 🇧🇩                    |
| `/help`     | Instructions & tips                                      |
| `/stats`    | Bot stats (admin only)                                   |
| `/live`     | 📈 Live traffic — newest SMS seen on public numbers       |
| `/country <name>` | 🔎 Find a country (typos & aliases like `usa`, `uk` work) |
| `/ping`     | Liveness check                                           |

---

## 🧩 Supported free sources

| Source                   | Countries (live) | Message text | Notes                                   |
|--------------------------|------------------|--------------|-----------------------------------------|
| `temp-number.com`        | ~18 with numbers | ✅ full text | paginated (up to 120 numbers/country); ~210 listed countries are empty, the bot hides them after a background check |
| `receivesms.co`          | ~25              | ✅ full text | paginated; shows "last activity" per number |
| `smss.net`               | ~16              | ✅ full text | no timestamps on messages               |
| `sms-online.co`          | 4 (US, UK, SE, MY) | ✅ full text |                                       |
| `receive-sms-online.info`| 3 (SE, FI, NL)   | ✅ via JSON  | often empty inboxes                     |

Together that is **~48 unique countries and ~4,900 numbers** (numbers change daily).
Country names are normalised (`Czech`/`Czechia`, `USA`/`United States`…) so Auto mode
merges the same country from several sites. Country buttons show how many numbers
each has, biggest first.

> These are *all* the free, scrapable public sources I could verify. Others
> (sms24.me, receive-smss.com, getfreesmsnumber…) block bots with Cloudflare, need a
> login/captcha, hide part of the number, or render only in JavaScript.
> `mytempsms.com` is implemented but **off by default** (every code is masked as
> `******`); enable with `ENABLE_MASKED_SOURCES=1`.

`⚡ Auto` merges everything and picks whichever source has numbers for the
country you choose. Scrapers live in `scrapers.py` — each source is one class
with 3 methods (`list_countries`, `list_numbers`, `get_messages`), so adding a
new site takes ~30 lines.

---

## ⚙️ Configuration (`config.py` / env vars)

| Variable                 | Default | Meaning                                   |
|--------------------------|---------|-------------------------------------------|
| `BOT_TOKEN`              | —       | Token from @BotFather (**required**)      |
| `ADMIN_IDS`              | —       | Comma-separated user IDs with /stats      |
| `POLL_INTERVAL`          | `8`     | Seconds between inbox checks              |
| `DEFAULT_WATCH_SECONDS`  | `900`   | Watch duration per number (15 min)        |
| `EXTEND_SECONDS`         | `600`   | "+10 min" button amount                   |
| `MAX_ACTIVE_PER_USER`    | `2`     | Max numbers one user watches at once      |
| `MAX_WATCH_SECONDS`      | `3600`  | Hard cap for one watcher (after extends)  |
| `MAX_NUMBERS_PER_COUNTRY`| `120`   | Numbers loaded per country per source     |
| `MAX_PAGES`              | `6`     | Listing pages followed per country        |
| `NUMBERS_PER_PAGE`       | `10`    | Buttons per page in the number list       |
| `WARMUP_INTERVAL_MIN`    | `30`    | How often empty countries are re-checked  |
| `MAX_CONSECUTIVE_ERRORS` | `5`     | Failures before a watcher gives up        |
| `PORT`                   | —       | If set, bot also serves `/health` (web hosts) |
| `HISTORY_FILE`           | `otp_history.jsonl` | Where received SMS are logged |
| `LANGS_FILE`             | `langs.json`        | Per-user language choices     |

---

## 🏠 Running it 24/7

Everything you need is already in this folder: `Dockerfile`, `render.yaml`,
`railway.json`, `Procfile`, `systemd/otpbot.service`, `.env.example`.

**Option A — Render.com (free web service) — step by step:**
1. Push this folder to a GitHub repo (private is fine).
2. [dashboard.render.com](https://dashboard.render.com) → **New → Blueprint** → connect GitHub
   (allow access to the repo) → pick the repo. Render reads `render.yaml`.
3. When asked, paste **`BOT_TOKEN`** (from @BotFather). Optional: `ADMIN_IDS` = your Telegram id.
   *The token lives only in Render's dashboard — never commit it.*
4. Click **Apply**. The first build takes ~2–4 min. Logs should show `Logged in as @yourbot`.
5. Open the bot in Telegram → `/start`.
6. **Keep it awake:** Render's free web services sleep after 15 min without inbound traffic,
   and a sleeping bot forwards no OTPs. The bot pings its own public URL every 10 min
   (`KEEP_ALIVE=1`). For a reliable backup add a free monitor on
   `https://<your-service>.onrender.com/health` every 5 min
   ([UptimeRobot](https://uptimerobot.com) / cron-job.org).

What to expect on the free plan:
- 750 free instance-hours/month per workspace = enough for **one** always-on service.
- Render may restart the service at any time; the filesystem is wiped on restart, so
  watchers that are running stop, and language choices / history reset. Just press
  *Get a free number* again. (A paid instance + disk removes this.)
- Don't run the same bot token anywhere else at the same time (Telegram allows one poller).
- Python is pinned to 3.12 (`.python-version` + `PYTHON_VERSION`) because Render's default
  for new services is 3.14, which this project hasn't been tested on.

**Option B — Railway (free trial credit; check current pricing):**
1. Push to GitHub
2. [railway.app](https://railway.app) → **New Project → Deploy from GitHub**
3. Add env var `BOT_TOKEN` in the project settings
4. `railway.json` handles the start command

**Option C — your own VPS with Docker:**
```bash
docker build -t otpbot .
docker run -d --name otpbot --restart unless-stopped -e BOT_TOKEN=123456789:AAH... otpbot
```

**Option D — VPS with systemd:**
```bash
sudo mkdir -p /opt/telegram-otp-bot
sudo cp -r . /opt/telegram-otp-bot/
echo 'BOT_TOKEN=123456789:AAH...' | sudo tee /etc/otpbot.env
sudo cp systemd/otpbot.service /etc/systemd/system/
sudo systemctl enable --now otpbot
```

**Option E — your own PC:** just leave `python bot.py` running.

---

## 🔧 Troubleshooting

| Problem | Fix |
|---|---|
| No SMS arrives | The service you're verifying probably blocks virtual numbers. Try another number / source / country. |
| "The website stopped responding" | That source is down or redesigned. Try another source; run `test_scrapers.py` to see which are alive. |
| A source shows 0 numbers | Site currently has none for that country — it changes hourly. Try again later. |
| Code was already used by someone | Shared number — pick a freshly listed number and use the code instantly. |
| I want to add a source | Copy any class in `scrapers.py`, adjust selectors, add it to `SOURCES`. |

---

## 🔒 Privacy

- The bot stores only what it forwards (`otp_history.jsonl`, local file) for
  the `/history` command — no phone numbers of your own, no personal data.
- All traffic goes directly from your server to the free SMS websites; the bot
  never sees anything else.
- **You** are responsible for how you use these numbers. Respect the target
  services' terms of service.
