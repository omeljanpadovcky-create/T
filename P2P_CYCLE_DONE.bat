@echo off
cd /d "%~dp0"
if not exist "p2p_radar\.venv\Scripts\python.exe" (
  echo First run START_P2P_RADAR.bat
  pause
  exit /b 1
)
"p2p_radar\.venv\Scripts\python.exe" "p2p_radar\radar.py" cycle-done
pause
