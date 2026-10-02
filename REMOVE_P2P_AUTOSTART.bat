@echo off
powershell -NoProfile -ExecutionPolicy Bypass -Command "if(Get-ScheduledTask -TaskName 'MYSHKA_P2P_RADAR' -ErrorAction SilentlyContinue){Unregister-ScheduledTask -TaskName 'MYSHKA_P2P_RADAR' -Confirm:$false; Write-Host '[MYSHKA] Autostart removed.' -ForegroundColor Yellow}else{Write-Host '[MYSHKA] Autostart task not found.'}"
pause
