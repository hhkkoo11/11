@echo off
setlocal

set "SHORTCUT=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Mobile Input Sync.lnk"

if exist "%SHORTCUT%" (
  del "%SHORTCUT%"
  echo Startup disabled.
) else (
  echo Startup was not enabled.
)

echo.
pause
