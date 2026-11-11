# AU University Dating Telegram Bot 💖🤖

An interactive Telegram dating and chat bot built for university students using [`python-telegram-bot`](https://python-telegram-bot.org/) and PostgreSQL (`asyncpg`).

---

## 🌟 Features

- **Profile Creation & Customization**:
  - Step-by-step registration wizard (Name, Gender, Campus, Photo, Bio, Hobbies, Preferences).
  - Profile preview and interactive editor for updating details at any time.
- **Matchmaking & Discovery**:
  - Filter candidates by preference (Male, Female, Both).
  - Session-aware matching that avoids repeating skipped profiles.
  - Mutual like detection ("It's a Match! 🎉") with real-time notifications.
- **Direct Anonymous Chat Relay**:
  - Connected users can chat in real time directly through the bot.
  - Seamless relay of text messages and photos.
  - End chat at any time using `/stop`.
- **Chat Requests**:
  - Send direct chat requests to matched users.
  - View and manage pending requests using `/requests`.
- **Reporting & Safety**:
  - Users can report inappropriate behavior directly from an active chat or profile card.
  - Direct command support: `/report <user_id> <reason>`.
  - Instant admin alert upon report submission.
- **Comprehensive Admin Suite (`/admin`)**:
  - **Gender Statistics (`/stats`)**: Breakdown of boys vs. girls counts, percentage ratios, and 24h registration metrics.
  - **Real-Time Match Alerts**: Instant notifications sent to the admin when two users match, complete with profile links and chat shortcuts.
  - **Conversation Logging (`/chatlogs`)**: Relayed chat messages (texts and photos) are stored in PostgreSQL for security and privacy audits, accessible via `/chatlogs` or the Admin Panel.
  - **User Management**: View full profiles, ban/unban, inspect swipes, and search users by ID/username/name.
  - **System Logs & Reports**: Inspect 24h activity, review reports, and take disciplinary actions.
  - **Dual Broadcast Modes**: Broadcast via reply command or guided multi-step wizard.
- **Flexible Execution Modes**:
  - **Polling mode**: Automatic default for local testing and debugging (zero HTTPS setup required).
  - **Webhook mode**: Production-ready webhook server via `aiohttp` for cloud platforms (Render, Heroku, VPS).

---

## 📋 Prerequisites

- **Python 3.11+**
- **PostgreSQL Database** (e.g., [Supabase](https://supabase.com), Neon, ElephantSQL, or local PostgreSQL)
- **Telegram Bot Token** from [@BotFather](https://t.me/BotFather)

---

## 🚀 Quick Start (Local Development)

### 1. Clone & Navigate
```bash
git clone https://github.com/filmon145/AU-UNIVERSITY-DATING-TELEGRAM-BOT.git
cd AU-UNIVERSITY-DATING-TELEGRAM-BOT
```

### 2. Set Up Virtual Environment & Install Dependencies
```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### 3. Configure Environment Variables
Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

Fill in your configuration:
```env
BOT_TOKEN=123456789:ABCdefGhIJKlmNoPQRsTUVwxyZ
ADMIN_USER_ID=your_numeric_telegram_user_id
DATABASE_URL=postgresql://user:password@localhost:5432/au_dating_db

# Optional settings:
CHECK_CHANNEL=false
DATABASE_SSL=auto
PORT=8080
```

> **Note**: Leave `RENDER_URL` empty to automatically start the bot in **Long-Polling mode**.

### 4. Run the Bot
```bash
python bot.py
```
Open Telegram, search for your bot username, and send `/start`!

---

## ☁️ Deployment (Webhook Mode on Render)

1. Fork or push this repository to GitHub.
2. In the [Render Dashboard](https://dashboard.render.com/):
   - Create a new **Web Service**.
   - Connect your GitHub repository.
   - Set **Runtime** to `Python 3`.
   - Set **Build Command**: `pip install -r requirements.txt`
   - Set **Start Command**: `python bot.py`
3. Add Environment Variables in Render:
   - `BOT_TOKEN`: Your Telegram Bot token.
   - `DATABASE_URL`: Your production PostgreSQL connection string (e.g. Supabase pooler URL).
   - `ADMIN_USER_ID`: Your Telegram numeric user ID.
   - `RENDER_URL`: Your Render service URL (e.g. `https://au-dating-bot.onrender.com`).
   - `PORT`: `8080` (or Render's `$PORT`).
4. Deploy the service. The bot will automatically configure its webhook with Telegram and start listening.

---

## 🐳 Docker Deployment

You can build and run using Docker:
```bash
docker build -t au-dating-bot .
docker run --env-file .env -p 8080:8080 au-dating-bot
```

---

## 📖 Bot Commands

| Command | Description | Access |
|---|---|---|
| `/start` | Start registration or open the main menu | All Users |
| `/find` | Browse profiles and find matches | Registered Users |
| `/myprofile` | View and edit your profile card | Registered Users |
| `/settings` | Update matching preferences (Male / Female / Both) | Registered Users |
| `/stop` | Disconnect from the current active chat | In-Chat Users |
| `/report` | Report current chat partner or `/report <id> <reason>` | All Users |
| `/requests` | View and accept/decline pending chat requests | All Users |
| `/admin` | Open interactive administrative control panel | Admin Only |
| `/stats` | View real-time boys & girls statistics, ratios, and 24h activity | Admin Only |
| `/chatlogs` | Inspect conversation logs (`/chatlogs <user>` or `/chatlogs <u1> <u2>`) | Admin Only |
| `/broadcast` | Reply to any message with `/broadcast` to send to all users | Admin Only |
| `/debug` | Check database connectivity and table stats | Admin Only |