@echo off
echo Stopping any running Peak Arena bot processes...
taskkill /F /FI "WINDOWTITLE eq Peak Arena Reel Automation Bot*" >nul 2>&1
for /f "tokens=2" %%i in ('wmic process where "commandline like '%%bot.py%%'" get processid ^| findstr /r "[0-9]"') do (
    echo Killing PID %%i
    taskkill /F /PID %%i >nul 2>&1
)
echo Done.
pause
