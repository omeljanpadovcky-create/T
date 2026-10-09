@echo off
setlocal
cd /d "%~dp0"
echo ==================================================
echo      CRYPTO MYSHKA LIVE - CONTINUOUS LOCAL WATCH
echo ==================================================
echo.
echo This opens a persistent live watcher on this PC.
echo Use Ctrl+C to stop. This DOES NOT place any trades.
echo.

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PYTHON_CMD=py"
) else (
  set "PYTHON_CMD=python"
)

%PYTHON_CMD% -m pip install --disable-pip-version-check requests==2.32.5 yt-dlp imageio-ffmpeg
if errorlevel 1 (
  echo Package installation failed. Check Python and internet access.
  pause
  exit /b 1
)

if not defined OPENAI_API_KEY if not defined MYSHKA_OLLAMA_URL (
  echo No vision AI configured. Stream availability will be checked,
  echo but no chart screenshots will be analyzed.
  echo You can set OPENAI_API_KEY or local MYSHKA_OLLAMA_URL.
)
if not defined MYSHKA_YOUTUBE_BROWSER (
  echo If YouTube blocks automated checks, set MYSHKA_YOUTUBE_BROWSER
  echo to your local browser name: chrome, edge or firefox.
)
echo.
if not defined LIVE_CAPTURE_INTERVAL set "LIVE_CAPTURE_INTERVAL=15"
echo Channel checks: every 15 seconds when YouTube responds.
echo Optional AI frame analysis interval: %LIVE_CAPTURE_INTERVAL% sec per active stream.
echo WARNING: OpenAI vision and speech recognition can create significant API costs.
echo The monitor records observations only and never places trades.
echo.
echo Opening LOCAL dashboard at http://127.0.0.1:8765/youtube-analysts.html#liveMonitor
start "CryptoMyshka Local Dashboard" /min %PYTHON_CMD% -m http.server 8765 --bind 127.0.0.1
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:8765/youtube-analysts.html#liveMonitor"
echo.
%PYTHON_CMD% crypto_myshka\rapid_live_watch.py --interval 15
pause
