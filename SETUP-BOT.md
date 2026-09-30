# BWU Portal Telegram Bot

Everything lives in **this project folder**: the Telegram bot, the portal client,
the captcha OCR engine (ddddocr + OpenCV — **no AI API**), and start/stop scripts.

Multi-user: every user logs in with **their own** portal credentials. Reports are sent as
**Telegram Rich Messages** (`sendRichMessage`): real `<table>` grids, `<details>` expandables,
a `<tg-slideshow>` banner carousel, and `<tg-button-row>` in-message buttons.

## Commands (only these two)
| Command | What it does |
|---|---|
| `/login STUDENT_CODE:PASSWORD` | log in (also `/login STUDENT_CODE PASSWORD`) |
| `/logout` | end your portal session (or the 🚪 button) |

Everything else is **buttons** (Dashboard, Fees & Payments, Marks with semester picker,
Attendance, Notices, Logout, Menu).

## Run on the VPS

```bash
rsync -a ./ user@vps:/opt/bwu_portal/
ssh user@vps
cd /opt/bwu_portal
nano .env              # created automatically on first start; set BOT_TOKEN
./start.sh             # starts detached (nohup) — safe to close the window
./stop.sh              # stops the bot
```

First `./start.sh` creates `.venv`, installs `requirements.txt`, and creates `.env` from
`.env.example` (set `BOT_TOKEN`, then start again). The bot keeps running after you close
the terminal/SSH window. To auto-start after a VPS reboot, add:

```
@reboot /opt/bwu_portal/start.sh
```

with `crontab -e`.

## Config (`.env`)
| Key | Meaning |
|---|---|
| `BOT_TOKEN` | from @BotFather |
| `ADMIN_USER_ID` | admin Telegram id (default 6515961910) |
| `SESSION_TTL_MIN` | how long each user's portal login is held/reused (3–5 typical) |
| `TZ`, `DIGEST_AT` | optional daily digest for logged-in users (empty = off) |
| `ATTENDANCE_THRESHOLD`, `FEE_WARN_DAYS` | alert thresholds |
| `HTTP_TIMEOUT`, `LOGIN_RETRIES` | portal timeout / captcha attempts |
| `TELEGRAM_EFFECT_ID` | optional Premium message effect |

## Multi-user & sessions
- Any Telegram user can use the bot; each login is bound to that user's id with an isolated
  portal session (`PHPSESSID`) and its own captcha solve
- Logins are **held for `SESSION_TTL_MIN` minutes** (default 5, inside the server's ~10-min
  window) so repeated taps don't re-solve captchas. After that the entry — credentials and
  client alike — is **evicted from memory** (background sweeper every 30 s, HTTP session
  closed), so RAM can never accumulate users; the user simply `/login`s again
- `/logout` (or 🚪 → ✅) wipes the stored credentials instantly; credentials live in memory only

## Admin (6515961910)
⚙️ panel in the menu: live stats, 📣 broadcast to all logged-in users, 🧹 clear sessions.

## Files
```
BWU_portal/
├── bot.py            aiogram handlers, rich send/edit, admin panel, digest
├── sessions.py       per-user login store with TTL hold
├── portal.py         captcha login + page fetch client
├── parsers.py        regex parsers (dashboard / payments / marks)
├── messages.py       Rich HTML builders (tables, details, slideshow, buttons)
├── ocr.py            captcha solver (test: python ocr.py image.png)
├── config.py         .env loader
├── requirements.txt
├── .env.example
├── start.sh          start detached (nohup + bot.pid, no log files)
├── stop.sh           stop the bot
└── SETUP-BOT.md      this guide
```

## Notes
- Built on **aiogram 3** (async dispatcher) + **arequest** (async portal client) + **ddddocr** OCR
- The bot **replies to your messages** (quoted) instead of sending standalone bubbles, and offers a
  **persistent keyboard** above the message box (Dashboard / Fees / Marks / Attendance / Notices /
  Logout / Admin) alongside the inline buttons
- Student code is forced **UPPERCASE** in `/login` (password untouched)
- Dashboard widgets (attendance, fee, activities, exam) load in one message — page fetches run in
  parallel and the final edit has multiple fallbacks, so the message can't get stuck on a
  "Loading…" stage
- **Custom Premium emoji**: all message-body emojis are sent as custom emoji
  (`<tg-emoji emoji-id>` in rich messages, `custom_emoji` entities in plain/progress texts;
  ID map in `emoji.py`). Button labels stay normal emoji (Telegram buttons can't show custom ones)
- **Logging is disabled** — nothing is written to disk (no `bot.log`); to debug, run
  `python bot.py` in the foreground temporarily
- HTTP runs on **`arequest`** (async, requests-like) — no `requests` dependency
- **Live status edits**: slow actions update the same message through stages — e.g. login shows
  `🚀 Start login… → 🖼️ Fetching captcha… → 🧩 Solving captcha… → 🔑 Submitting credentials… →
  ✅ Login OK! → 📊 Loading dashboard… → 🏠 Main dashboard` (rich message replaces the status)
- **Marks page is slow (~1 min)** — the message edits to `⏳ Loading marks…` first
- Login retry: up to `LOGIN_RETRIES` fresh captchas per login (>99% measured success)
- If `sendRichMessage` is unavailable the bot auto-falls back to plain formatted messages
- Use only with your own portal account; credentials are held in RAM while logged in
