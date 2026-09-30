$ErrorActionPreference='Continue'

$app=$null
try {
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
} catch {}
if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path $fallback){$app=$fallback}
}
if(-not $app){throw 'ASTRA project folder not found.'}

$pidFile=Join-Path $app '.mt5-shadow.pid'
if(Test-Path $pidFile){
  try {
    $pid=[int](Get-Content $pidFile -Raw)
    Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
    Write-Host ('[OK] MT5 Shadow Collector stopped. PID '+$pid) -ForegroundColor Green
  } catch {
    Write-Host '[WARN] Could not stop stored PID.' -ForegroundColor Yellow
  }
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
} else {
  Write-Host '[INFO] MT5 Shadow Collector PID file not found.'
}
