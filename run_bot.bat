@echo off
title Peak Arena Reel Automation Bot
cd /d "%~dp0"

if not exist ".env" (
    echo Creating .env from template...
    copy .env.example .env
    echo Please edit .env file and paste your TELEGRAM_BOT_TOKEN!
    notepad .env
    pause
    exit /b
)

if not exist "venv\Scripts\python.exe" (
    echo Setting up Python virtual environment...
    python -m venv venv
)

echo Checking & installing dependencies...
venv\Scripts\pip install -r requirements.txt

echo.
echo Starting Peak Arena Telegram Bot...
venv\Scripts\python bot.py

pause
