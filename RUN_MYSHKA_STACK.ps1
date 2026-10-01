param(
  [switch]$NoMT5
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - RUN FULL STACK ' -ForegroundColor Yellow
Write-Host ' ASTRA + FREQTRADE + MT5 SHADOW + XCHECKS ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=$null
$prevEap=$ErrorActionPreference
$ErrorActionPreference='Continue'
try {
  $raw = docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
} catch {}
finally {
  $ErrorActionPreference=$prevEap
}

if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback 'api.py')){$app=$fallback}
}
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){
  throw 'ASTRA project folder not found.'
}

Set-Location $app
Write-Host ('[OK] Project: '+$app) -ForegroundColor Green

Write-Host '[1/7] Starting Freqtrade + ASTRA...'
$prevEap=$ErrorActionPreference
$ErrorActionPreference='Continue'
try {
  docker compose up -d freqtrade astra
  $dockerRc=$LASTEXITCODE
} finally {
  $ErrorActionPreference=$prevEap
}
if($dockerRc -ne 0){throw 'docker compose up failed.'}
Write-Host '[OK] Docker services requested.' -ForegroundColor Green

if(-not $NoMT5){
  Write-Host '[2/7] Starting MT5 Shadow Collector...'
  $mt5Start=Join-Path $app 'START_MT5_SHADOW_V1.ps1'
  if(Test-Path $mt5Start){
    & powershell -ExecutionPolicy Bypass -File $mt5Start
    if($LASTEXITCODE -ne 0){
      Write-Host '[WARN] MT5 Shadow Collector start returned non-zero. ASTRA can still run with MT5=NO_DATA.' -ForegroundColor Yellow
    }
  } else {
    Write-Host '[WARN] START_MT5_SHADOW_V1.ps1 not found. Continuing with MT5=NO_DATA.' -ForegroundColor Yellow
  }
} else {
  Write-Host '[2/7] MT5 Shadow skipped by -NoMT5.' -ForegroundColor Yellow
}

Write-Host '[3/7] Waiting for ASTRA health...'
$health=$null
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 2
  try {
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){break}
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){
  throw 'ASTRA did not become healthy.'
}
Write-Host '[OK] ASTRA health=ok' -ForegroundColor Green

Write-Host '[4/7] Reading ASTRA bridge token...'
$token=$null
$prevEap=$ErrorActionPreference
$ErrorActionPreference='Continue'
try {
  $envLines=docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' 2>$null
  if($LASTEXITCODE -eq 0){
    $line=$envLines | Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} | Select-Object -First 1
    if($line){$token=$line -replace '^MYSHKA_BRIDGE_TOKEN=',''}
  }
} finally {
  $ErrorActionPreference=$prevEap
}
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}
Write-Host '[OK] Token present (not displayed).' -ForegroundColor Green

Write-Host '[5/7] Checking execution mode...'
$live=$null
$dry=$null
try {$live=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-live/status' -Headers $headers -TimeoutSec 10}catch{}
try {$dry=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-dryrun/status' -Headers $headers -TimeoutSec 10}catch{}

$mode='UNKNOWN'
if($live -and $live.local_live_enabled -eq $true){
  $mode='LIVE_ARMED'
}elseif($dry -and $dry.local_dry_run -eq $true){
  $mode='DRY_RUN'
}elseif($live){
  $mode='LIVE_BRIDGE_DISARMED'
}

Write-Host ('Execution mode: '+$mode) -ForegroundColor Cyan
if($live){
  Write-Host ('LIVE max stake: '+[string]$live.max_stake_usdt+' USDT')
  Write-Host ('LIVE max leverage: '+[string]$live.max_leverage+'x')
  Write-Host ('LIVE events: '+[string]$live.events)
}

Write-Host '[6/7] Checking analysis agents...'
$ext=$null
$mt5=$null
try {$ext=Invoke-RestMethod 'http://127.0.0.1:8088/external-market/status' -Headers $headers -TimeoutSec 10}catch{}
try {$mt5=Invoke-RestMethod 'http://127.0.0.1:8088/mt5-shadow/status' -Headers $headers -TimeoutSec 10}catch{}

if($ext){
  Write-Host ('External XCheck: '+$ext.mode+' · cached='+[string]$ext.investing_cached_symbols+' · macro='+[string]$ext.macro_cached) -ForegroundColor Green
}else{
  Write-Host '[WARN] External Market Shadow endpoint unavailable.' -ForegroundColor Yellow
}

if($mt5){
  Write-Host ('MT5 Shadow: '+$mt5.mode+' · token='+[string]$mt5.token_present+' · cache='+[string]$mt5.cache_symbols) -ForegroundColor Green
}else{
  Write-Host '[WARN] MT5 Shadow endpoint unavailable.' -ForegroundColor Yellow
}

Write-Host '[7/7] Recent LIVE bridge events...'
if($live){
  try {
    $recent=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-live/recent?limit=5' -Headers $headers -TimeoutSec 10
    if($recent.items -and @($recent.items).Count -gt 0){
      foreach($ev in @($recent.items)){
        Write-Host (' - '+[string]$ev.status+' · '+[string]$ev.pair+' · '+[string]$ev.side+' · '+[string]$ev.source)
      }
    }else{
      Write-Host ' - no LIVE bridge events yet'
    }
  }catch{
    Write-Host ' - recent endpoint unavailable'
  }
}else{
  Write-Host ' - live bridge status unavailable'
}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' MYSHKA STACK IS RUNNING ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Mode: '+$mode)
Write-Host 'Signals/scan logic: ASTRA'
Write-Host 'Execution: Freqtrade bridge'
Write-Host 'XChecks: Binance + Investing + Macro + MT5 Shadow'
Write-Host 'Forward evaluation: 5m / 10m / 15m'
Write-Host 'Telegram: enabled by existing ASTRA configuration'
Write-Host ''
if($mode -eq 'LIVE_ARMED'){
  Write-Host 'REAL-MONEY LIVE IS ARMED. The next qualifying ASTRA ENTER may be routed to Freqtrade.' -ForegroundColor Red
}elseif($mode -eq 'DRY_RUN'){
  Write-Host 'DRY-RUN is active. Trades remain simulated.' -ForegroundColor Yellow
}else{
  Write-Host 'Execution is not confirmed LIVE. No automatic mode change was made by this RUN script.' -ForegroundColor Yellow
}
