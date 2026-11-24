@echo off
title Peak Arena Reel Automation Engine
cd /d "%~dp0"
echo =====================================================================
echo                PEAK ARENA VIRAL REEL ENGINE
echo =====================================================================
echo [1] Hijack Reel from URL (Paste Instagram / YouTube Shorts link)
echo [2] Hijack Reference Reel (Natural flow, voice inpainting, no extra bars)
echo [3] Generate Esports Tournament Reel (With match cards + voiceover)
echo [4] Start Telegram Bot Server (Make reels from mobile phone anytime)
echo =====================================================================
set /p choice="Enter option (1, 2, 3, or 4, default is 1): "

if "%choice%"=="1" (
    set /p reel_url="Paste Reel / Shorts URL: "
    echo Downloading and hijacking reel...
    call "venv\Scripts\python.exe" auto_reel_hijacker.py --url "%reel_url%"
) else if "%choice%"=="3" (
    echo Generating tournament promo reel...
    call "venv\Scripts\python.exe" generate_reference_matched_reel.py
) else if "%choice%"=="4" (
    echo Starting Telegram Bot...
    call "venv\Scripts\python.exe" telegram_bot.py
) else (
    echo Hijacking reference reel...
    call "venv\Scripts\python.exe" auto_reel_hijacker.py
)

echo =====================================================================
echo Done! Check the output folder for your rendered reel.
echo =====================================================================
pause
