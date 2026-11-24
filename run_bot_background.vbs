' run_bot_background.vbs — Runs Peak Arena Bot silently in background
Set WshShell = CreateObject("WScript.Shell")
strPath = WScript.ScriptFullName
Set fso = CreateObject("Scripting.FileSystemObject")
Set file = fso.GetFile(strPath)
strFolder = fso.GetParentFolderName(file)

' Launch venv\Scripts\python.exe bot.py without a visible command prompt window (0 = hide window)
WshShell.CurrentDirectory = strFolder
WshShell.Run "cmd /c venv\Scripts\python.exe bot.py >> temp\bot.log 2>&1", 0, False
