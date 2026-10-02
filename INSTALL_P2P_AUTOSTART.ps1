$ErrorActionPreference='Stop'
$task='MYSHKA_P2P_RADAR'
$bat=Join-Path $PSScriptRoot 'START_P2P_RADAR.bat'
if(-not (Test-Path $bat)){throw "START_P2P_RADAR.bat not found"}
$arg='/c start "" /min "'+$bat+'"'
$action=New-ScheduledTaskAction -Execute 'cmd.exe' -Argument $arg
$trigger=New-ScheduledTaskTrigger -AtLogOn
$settings=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -Description 'MYSHKA P2P Radar + Telegram alerts' -Force | Out-Null
Start-ScheduledTask -TaskName $task
Write-Host '[MYSHKA] P2P Radar autostart installed and started.' -ForegroundColor Green
