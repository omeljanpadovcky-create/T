@echo off
setlocal
cd /d "%~dp0"
title Crypto Myshka - Local PC

echo ==================================================
echo        CRYPTO MYSHKA - LOCAL PC MODE
echo ==================================================
echo This runs the existing radar and Telegram menu on this PC.
echo It does NOT place trades. OTC directions remain disabled until
echo a verified Pocket Option OTC quote source is connected.
echo Keep this window open while the bot is running.
echo.

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PY=py -3"
) else (
  where python >nul 2>nul
  if errorlevel 1 (
    echo Python 3 was not found. Install Python 3.11 or newer from python.org
    echo and enable "Add Python to PATH", then run this file again.
    pause
    exit /b 1
  )
  set "PY=python"
)

if not exist "p2p_radar\.env" if not exist ".env" (
  copy /Y "p2p_radar\.env.example" "p2p_radar\.env" >nul
  echo Created p2p_radar\.env.
  echo.
  echo ACTION REQUIRED:
  echo 1. Open p2p_radar\.env in Notepad.
  echo 2. Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID.
  echo 3. Save it, then run START_MYSHKA_PC.bat again.
  echo Never send your bot token to anyone or commit it to GitHub.
  start "" notepad "p2p_radar\.env"
  pause
  exit /b 0
)

findstr /C:"PASTE_YOUR_TELEGRAM_BOT_TOKEN_HERE" "p2p_radar\.env" >nul 2>nul
if not errorlevel 1 (
  echo Telegram token is still a placeholder in p2p_radar\.env.
  start "" notepad "p2p_radar\.env"
  pause
  exit /b 1
)

echo Installing/checking Python packages...
%PY% -m pip install --disable-pip-version-check -r "p2p_radar\requirements.txt"
if errorlevel 1 (
  echo Package installation failed. Check Python and internet access.
  pause
  exit /b 1
)

echo.
echo Starting Myshka. Do not close this window to keep it running.
echo Stop with Ctrl+C.
echo ==================================================
%PY% "p2p_radar\radar.py"
echo.
echo Myshka stopped or exited. Review any error above.
pause
