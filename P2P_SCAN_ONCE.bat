@echo off
cd /d "%~dp0"
if not exist "p2p_radar\.venv\Scripts\python.exe" (
  call START_P2P_RADAR.bat
  exit /b
)
"p2p_radar\.venv\Scripts\python.exe" "p2p_radar\radar.py" --once
pause
