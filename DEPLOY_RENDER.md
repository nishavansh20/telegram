# Deploy Peak Arena Telegram Bot on Render (Free 24/7)

## Steps:

### 1. Push to GitHub
Create a GitHub repository (e.g. `peak-arena-reel-bot`) and push this folder:
```bash
git init
git add .
git commit -m "Peak Arena Reel Bot"
git branch -M main
git remote add origin https://github.com/<YOUR_USERNAME>/peak-arena-reel-bot.git
git push -u origin main
```

### 2. Create Service on Render
1. Go to [dashboard.render.com](https://dashboard.render.com/) and click **New +** -> **Web Service**.
2. Select your `peak-arena-reel-bot` GitHub repository.
3. Configuration:
   - **Name**: `peak-arena-bot`
   - **Runtime**: `Docker` (Render auto-detects `Dockerfile`)
   - **Instance Type**: `Free`
4. Add Environment Variable:
   - Key: `TELEGRAM_BOT_TOKEN`
   - Value: `<YOUR_BOTFATHER_TOKEN>`
5. Click **Deploy Web Service**.

---

### 3. Keep Render Free Tier Awake 24/7 (Cron Job Ping)
Render free services sleep after 15 min without traffic. Set up a free 5-10 min cron ping:

1. Copy your Render web service URL (e.g. `https://peak-arena-bot.onrender.com`).
2. Go to [cron-job.org](https://cron-job.org/) (or [uptimerobot.com](https://uptimerobot.com/)).
3. Create a cron job:
   - **URL**: `https://peak-arena-bot.onrender.com/ping`
   - **Schedule**: Every 10 minutes
4. When pinged, the server returns:
```json
{
  "status": "pong",
  "message": "🏓 Peak Arena Reel Bot is awake and active!",
  "ping_count": 42,
  "uptime": "2h 15m 10s",
  "timestamp": "2026-11-24 17:45:00 UTC"
}
```
And logs: `[CRON PING #42] Keepalive ping received...` in Render dashboard.

Your bot will never sleep!
