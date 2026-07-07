@echo off
setlocal
cd /d "%~dp0"

set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "SHORTCUT=%STARTUP%\Mobile Input Sync.lnk"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut('%SHORTCUT%'); $s.TargetPath='powershell.exe'; $s.Arguments='-NoProfile -ExecutionPolicy Bypass -File \"%~dp0start_phone_input_sync_hidden.ps1\"'; $s.WorkingDirectory='%~dp0'; $s.WindowStyle=7; $s.Save()"

echo Startup enabled.
echo This PC will start Mobile Input Sync automatically after you sign in.
echo.
pause
