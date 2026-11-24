@echo off
title Peak Arena Telegram Bot Server
cd /d "%~dp0"
echo =====================================================================
echo                PEAK ARENA TELEGRAM BOT SERVER
echo =====================================================================
echo Starting Telegram bot listener...
echo Send Instagram Reel or Shorts link to your bot from any phone/device!
echo =====================================================================
"venv\Scripts\python.exe" telegram_bot.py
pause
