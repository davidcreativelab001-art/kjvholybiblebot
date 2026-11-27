# KJV Holy Bible Bot (@kjvholybiblebot) — Deploy Guide

Full bot: Daily Verse, Bible Search, Read a Chapter, Topics, 14 Devotionals,
Bible Quiz with scores, Prayer Requests, hidden Admin panel.

## 1. Create the bot
Talk to @BotFather → /newbot → name it → copy the token.

## 2. Railway setup
- New project → deploy from these files (bot.py + requirements.txt)
- Variables:
  - `BOT_TOKEN` = token from BotFather
  - `ADMIN_IDS` = your Telegram numeric ID (get it by messaging @userinfobot). Comma-separate for more admins.
  - Optional: `DAILY_HOUR=7` (Africa/Lagos), `SUPPORT_CONTACT=@davidcreativelab`
- Start command: `python bot.py`
- Add a Railway Volume mounted at the app folder if you want the SQLite DB
  (users, prayers, quiz scores) to survive redeploys. Without a volume it resets on redeploy.

## 3. Test
- /start — welcome + Verse of the Day + menu
- Menu shows only /start, /menu, /help. /admin works typed in private chat, admin-only.
- Try: Search `John 3:16`, keyword `faith`, Read `Psalms 23`, a Quiz round, a Prayer Request
  (it should arrive in your admin chat instantly).

## Notes
- Bible text: bible-api.com (KJV only) — free, no API key.
- Keyword search: bolls.life, with built-in topical fallback if it is unreachable.
- Daily verse auto-sends at 07:00 Africa/Lagos to users with Daily Verse ON in Settings.
