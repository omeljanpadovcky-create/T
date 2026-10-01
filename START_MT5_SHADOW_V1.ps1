$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - START MT5 SHADOW COLLECTOR V1 ' -ForegroundColor Yellow
Write-Host ' READ ONLY - NO MT5 ORDER EXECUTION ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=$null
try {
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
} catch {}
if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback 'api.py')){$app=$fallback}
}
if(-not $app){throw 'ASTRA project folder not found.'}
Set-Location $app

$collector=Join-Path $app 'mt5_shadow_collector.py'
$envFile=Join-Path $app '.env.live-armed'
$pidFile=Join-Path $app '.mt5-shadow.pid'
$outLog=Join-Path $app 'mt5-shadow.out.log'
$errLog=Join-Path $app 'mt5-shadow.err.log'

if(-not (Test-Path $collector)){throw 'mt5_shadow_collector.py not found.'}
if(-not (Test-Path $envFile)){throw '.env.live-armed not found.'}

$prevEap=$ErrorActionPreference
$ErrorActionPreference='Continue'
try {
  cmd /c 'python -c "import MetaTrader5; print(''MetaTrader5 package OK'')"'
  $mt5ImportRc=$LASTEXITCODE
} finally {
  $ErrorActionPreference=$prevEap
}
if($mt5ImportRc -ne 0){throw 'MetaTrader5 Python package is not installed.'}

$tokenLine=Get-Content $envFile | Where-Object {$_ -match '^MT5_SHADOW_TOKEN='} | Select-Object -First 1
if(-not $tokenLine){throw 'MT5_SHADOW_TOKEN missing from .env.live-armed'}
$token=($tokenLine -replace '^MT5_SHADOW_TOKEN=','').Trim().Trim('"').Trim("'")
if(-not $token){throw 'MT5_SHADOW_TOKEN is empty.'}

if(Test-Path $pidFile){
  try {
    $oldPid=[int](Get-Content $pidFile -Raw)
    $old=Get-Process -Id $oldPid -ErrorAction SilentlyContinue
    if($old){
      Write-Host ('[INFO] Stopping old collector PID '+$oldPid)
      Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
      Start-Sleep -Seconds 1
    }
  } catch {}
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$env:MT5_SHADOW_TOKEN=$token
$env:MT5_SHADOW_HOST='0.0.0.0'
$env:MT5_SHADOW_PORT='8115'

Write-Host '[1/3] Starting Windows MT5 collector...'
$args=@($collector)
$p=Start-Process -FilePath 'python' -ArgumentList $args -WorkingDirectory $app -WindowStyle Hidden -RedirectStandardOutput $outLog -RedirectStandardError $errLog -PassThru

$p.Id | Set-Content $pidFile -Encoding ASCII
Write-Host ('[OK] PID '+$p.Id) -ForegroundColor Green

Write-Host '[2/3] Waiting for collector health...'
$health=$null
for($i=0;$i -lt 20;$i++){
  Start-Sleep -Milliseconds 750
  try {
    $health=Invoke-RestMethod 'http://127.0.0.1:8115/health' -TimeoutSec 3
    if($health.status -eq 'ok'){break}
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){
  Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
  Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
  $err=''
  if(Test-Path $errLog){$err=(Get-Content $errLog -Tail 20) -join [Environment]::NewLine}
  throw ('MT5 Shadow Collector did not start. '+$err)
}
if($health.mt5_imported -ne $true){
  throw 'Collector started but MetaTrader5 Python package failed to import.'
}
Write-Host '[OK] Collector health OK' -ForegroundColor Green

Write-Host '[3/3] Read-only MT5 snapshot probe...'
$headers=@{'X-MT5-SHADOW-TOKEN'=$token}
$probe=Invoke-RestMethod 'http://127.0.0.1:8115/snapshot?ticker=BTC' -Headers $headers -TimeoutSec 15

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - MT5 SHADOW COLLECTOR V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Probe status: '+[string]$probe.status)

if([string]$probe.status -eq 'READY'){
  $symbol = if($probe.PSObject.Properties.Name -contains 'symbol'){[string]$probe.symbol}else{'—'}
  $direction = if($probe.PSObject.Properties.Name -contains 'direction'){[string]$probe.direction}else{'—'}
  Write-Host ('MT5 symbol: '+$symbol)
  Write-Host ('Direction: '+$direction)

  if(($probe.PSObject.Properties.Name -contains 'terminal') -and $probe.terminal){
    $company = if($probe.terminal.PSObject.Properties.Name -contains 'company'){[string]$probe.terminal.company}else{'—'}
    $server = if($probe.terminal.PSObject.Properties.Name -contains 'server'){[string]$probe.terminal.server}else{'—'}
    Write-Host ('Company: '+$company)
    Write-Host ('Server: '+$server)
  }
} else {
  $reason = if($probe.PSObject.Properties.Name -contains 'reason'){[string]$probe.reason}else{'unknown'}
  Write-Host ('[WARN] MT5 snapshot is NO_DATA: '+$reason) -ForegroundColor Yellow
  Write-Host '[WARN] Collector stays running; ASTRA will safely use MT5=NO_DATA until terminal data becomes available.' -ForegroundColor Yellow
}

Write-Host 'READ ONLY: TRUE'
Write-Host 'MT5 trade execution: NOT IMPLEMENTED'
Write-Host ('PID file: '+$pidFile)
