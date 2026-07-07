@echo off
setlocal
cd /d "%~dp0"

echo Starting Mobile Input Sync...
echo.

netstat -ano | findstr /R /C:":8787 .*LISTENING" >nul
if %errorlevel%==0 (
  echo The desktop service is already running.
  if exist current_url.txt (
    echo.
    echo Phone URL:
    type current_url.txt
  )
  echo.
  pause
  exit /b 0
)

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0mobile_input_server.py"
) else (
  python "%~dp0mobile_input_server.py"
)

echo.
echo The service stopped.
pause
