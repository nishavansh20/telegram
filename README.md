# Peak Arena Reel Automation Telegram Bot 🎬

Automated video branding bot for **Peak Arena**. 
Send the Telegram bot any **Instagram Reel** or **YouTube Shorts** link (or upload any raw gaming video directly). The bot auto-downloads, resizes to vertical 9:16 (1080×1920), overlays branded top and bottom cards, replaces competitor app screenshots with the Peak Arena app screen, replaces spoken voice audio with "Peak Arena", and appends an Instagram Bio download outro screen!

---

## ⚡ What The Bot Automates

1. **Top Header Card (Cyan `#00e5ff` Outline)**:
   - Official Peak Arena shield logo on the left.
   - White bold title: `PEAK ARENA`
   - Cyan subtitle: `BATTLEGROUND TOURNAMENTS`
2. **Bottom Cards (Gold `#e5a93c` Outline)**:
   - Dynamic 3-Phase Match Info:
     - Phase 1: `JOIN THE BATTLE / ENTRY 15 INR | 14 INR PER KILL / 4-5 MATCHES`
     - Phase 2: `LEVEL UP YOUR GAME / SHOW YOUR SKILLS IN THE ARENA`
     - Phase 3: `READY TO ENTER? / PEAK ARENA IS CALLING`
   - Or customizable via user prompt!
3. **Competitor App Replacement**:
   - Replaces competitor app screenshots shown during the reel (e.g. 12s–16s) with the real Peak Arena tournament & wallet UI framed in rounded cyan.
4. **Voice Audio Replacement ("Peak Arena")**:
   - Ducks competitor name in audio track and punches in clean Hindi voice saying "Peak Arena" without altering background game sounds.
5. **Instagram Bio Outro**:
   - 3.2-second outro card displaying your Instagram Profile (`@_maxeddd`) with followers, bio bullets, and "DOWNLOAD APP FROM BIO LINK".

---

## 🚀 Running Locally (Windows)

1. Ensure `.env` contains:
   ```env
   TELEGRAM_BOT_TOKEN=9030505295:AAEm8aOHzGTiYlARK7ykfj2n8WUqJpvNwJE
   ```
2. Double-click **`run_bot.bat`**.
3. The bot connects and listens on Telegram!

---

## ☁️ Running on Cloud / Render.com

If deploying to Render or Docker, make sure to add:
- **Environment Variable**:
  - Key: `TELEGRAM_BOT_TOKEN`
  - Value: `9030505295:AAEm8aOHzGTiYlARK7ykfj2n8WUqJpvNwJE`

---

## 📲 How to Use in Telegram

### 1. Default Mode (Fully Automated)
Send the reel link:
```text
https://www.instagram.com/reel/C7.../
```
The bot automatically downloads, cuts, brands, swaps app screen, ducks voice, and adds the Instagram bio outro.

### 2. Custom Promotional Prompt
```text
https://www.instagram.com/reel/... | WIN ₹1000 TONIGHT | ENTRY 15 INR | 14 PER KILL
```

### 3. Custom Time Controls (Optional)
```text
https://www.instagram.com/reel/... | app: 11-15 | voice: 12-13.5 | insta: @_maxeddd
```

### 4. Send or Forward Video Directly
Attach any video file and put your prompt in the caption!

### 5. Bot Commands
- `/start` - Welcome message and quick start instructions.
- `/demo` - Render and send a sample reel.
- `/set_insta <handle>` - Change default Instagram handle on outro cards.
- `/help` - Command reference.
