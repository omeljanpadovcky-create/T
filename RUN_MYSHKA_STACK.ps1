param(
  [switch]$NoMT5
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$RUN_VERSION='V3-AUTOREPAIR'

function Get-Field {
  param(
    $Object,
    [string]$Name,
    $Default=$null
  )
  if($null -eq $Object){ return $Default }
  try {
    if($Object.PSObject.Properties.Name -contains $Name){
      $v=$Object.$Name
      if($null -ne $v){ return $v }
    }
  } catch {}
  return $Default
}

function Invoke-SafeRest {
  param(
    [string]$Uri,
    [hashtable]$Headers=@{},
    [int]$TimeoutSec=8
  )
  try {
    return Invoke-RestMethod -Uri $Uri -Headers $Headers -TimeoutSec $TimeoutSec
  } catch {
    return $null
  }
}

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - RUN FULL STACK ' -ForegroundColor Yellow
Write-Host (' RUN VERSION: '+$RUN_VERSION) -ForegroundColor Green
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

Write-Host '[1/8] Starting Freqtrade + ASTRA...'
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

$mt5Launch='SKIPPED'
if(-not $NoMT5){
  Write-Host '[2/8] Starting MT5 Shadow Collector...'
  $mt5Start=Join-Path $app 'START_MT5_SHADOW_V1.ps1'
  if(Test-Path $mt5Start){
    $prevEap=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    try {
      & powershell -ExecutionPolicy Bypass -File $mt5Start
      $mt5Rc=$LASTEXITCODE
    } finally {
      $ErrorActionPreference=$prevEap
    }
    if($mt5Rc -eq 0){
      $mt5Launch='STARTED'
      Write-Host '[OK] MT5 Shadow start script completed.' -ForegroundColor Green
    } else {
      $mt5Launch='NO_DATA_OR_START_WARNING'
      Write-Host '[WARN] MT5 Shadow did not fully initialize. ASTRA will continue with MT5=NO_DATA.' -ForegroundColor Yellow
    }
  } else {
    $mt5Launch='SCRIPT_MISSING'
    Write-Host '[WARN] START_MT5_SHADOW_V1.ps1 not found. Continuing with MT5=NO_DATA.' -ForegroundColor Yellow
  }
} else {
  Write-Host '[2/8] MT5 Shadow skipped by -NoMT5.' -ForegroundColor Yellow
}

Write-Host '[3/8] Checking Windows MT5 collector health/snapshot...'
$collectorHealth=Invoke-SafeRest 'http://127.0.0.1:8115/health' @{} 3
$collectorState='UNAVAILABLE'
$collectorReason=''
if($collectorHealth -and (Get-Field $collectorHealth 'status' '') -eq 'ok'){
  $collectorState='HEALTHY'
  $envFile=Join-Path $app '.env.live-armed'
  $mt5Token=$null
  if(Test-Path $envFile){
    $line=Get-Content $envFile | Where-Object {$_ -match '^MT5_SHADOW_TOKEN='} | Select-Object -First 1
    if($line){$mt5Token=($line -replace '^MT5_SHADOW_TOKEN=','').Trim().Trim('"').Trim("'")}
  }
  if($mt5Token){
    $snap=Invoke-SafeRest 'http://127.0.0.1:8115/snapshot?ticker=BTC' @{'X-MT5-SHADOW-TOKEN'=$mt5Token} 8
    if($snap){
      $snapStatus=[string](Get-Field $snap 'status' 'NO_DATA')
      if($snapStatus -eq 'READY'){
        $sym=[string](Get-Field $snap 'symbol' '—')
        $dir=[string](Get-Field $snap 'direction' '—')
        $terminal=Get-Field $snap 'terminal' $null
        $company=[string](Get-Field $terminal 'company' '—')
        $server=[string](Get-Field $terminal 'server' '—')
        Write-Host ('[OK] MT5 snapshot READY · '+$sym+' · '+$dir+' · '+$company+' · '+$server) -ForegroundColor Green
      } else {
        $collectorState='NO_DATA'
        $collectorReason=[string](Get-Field $snap 'reason' 'unknown')
        Write-Host ('[WARN] MT5 snapshot NO_DATA: '+$collectorReason) -ForegroundColor Yellow
      }
    } else {
      $collectorState='NO_DATA'
      $collectorReason='snapshot_endpoint_unavailable'
      Write-Host '[WARN] MT5 snapshot endpoint unavailable.' -ForegroundColor Yellow
    }
  } else {
    $collectorState='NO_DATA'
    $collectorReason='token_missing'
    Write-Host '[WARN] MT5 token not found in .env.live-armed.' -ForegroundColor Yellow
  }
} else {
  Write-Host '[WARN] MT5 collector health unavailable. ASTRA can still run.' -ForegroundColor Yellow
}

Write-Host '[4/8] Waiting for ASTRA health...'
$health=$null
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 2
  $health=Invoke-SafeRest 'http://127.0.0.1:8088/health' @{} 5
  if($health -and (Get-Field $health 'status' '') -eq 'ok'){break}
}

if(-not $health -or (Get-Field $health 'status' '') -ne 'ok'){
  Write-Host '[WARN] ASTRA health failed. Running automatic repair/rebuild...' -ForegroundColor Yellow

  $prevEap=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  try {
    Write-Host '--- ASTRA logs before repair ---' -ForegroundColor DarkYellow
    docker logs myshka-astra --tail 120 2>&1 | Select-Object -Last 120 | ForEach-Object { Write-Host $_ }

    Write-Host '--- Rebuilding ASTRA image ---' -ForegroundColor DarkYellow
    docker compose build astra 2>&1 | ForEach-Object { Write-Host $_ }
    $buildRc=$LASTEXITCODE

    if($buildRc -eq 0){
      Write-Host '--- Force recreating ASTRA ---' -ForegroundColor DarkYellow
      docker compose up -d --force-recreate astra 2>&1 | ForEach-Object { Write-Host $_ }
      $recreateRc=$LASTEXITCODE
    } else {
      $recreateRc=1
    }
  } finally {
    $ErrorActionPreference=$prevEap
  }

  if($buildRc -eq 0 -and $recreateRc -eq 0){
    $health=$null
    for($i=0;$i -lt 30;$i++){
      Start-Sleep -Seconds 2
      $health=Invoke-SafeRest 'http://127.0.0.1:8088/health' @{} 5
      if($health -and (Get-Field $health 'status' '') -eq 'ok'){break}
    }
  }

  if(-not $health -or (Get-Field $health 'status' '') -ne 'ok'){
    Write-Host '--- ASTRA logs after repair attempt ---' -ForegroundColor Red
    $prevEap=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    try {
      docker logs myshka-astra --tail 180 2>&1 | Select-Object -Last 180 | ForEach-Object { Write-Host $_ }
    } finally {
      $ErrorActionPreference=$prevEap
    }
    throw 'ASTRA still unhealthy after automatic rebuild. See logs above for the exact error.'
  }

  Write-Host '[OK] ASTRA recovered after automatic rebuild.' -ForegroundColor Green
}else{
  Write-Host '[OK] ASTRA health=ok' -ForegroundColor Green
}

Write-Host '[5/8] Reading ASTRA bridge token...'
$token=$null
$prevEap=$ErrorActionPreference
$ErrorActionPreference='Continue'
try {
  $envLines=docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' 2>$null
  $inspectRc=$LASTEXITCODE
  if($inspectRc -eq 0){
    $line=$envLines | Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} | Select-Object -First 1
    if($line){$token=($line -replace '^MYSHKA_BRIDGE_TOKEN=','').Trim()}
  }
} finally {
  $ErrorActionPreference=$prevEap
}
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}
Write-Host '[OK] Token present (not displayed).' -ForegroundColor Green

Write-Host '[6/8] Checking execution mode...'
$live=Invoke-SafeRest 'http://127.0.0.1:8088/freqtrade-live/status' $headers 10
$dry=Invoke-SafeRest 'http://127.0.0.1:8088/freqtrade-dryrun/status' $headers 10

$liveEnabled=[bool](Get-Field $live 'local_live_enabled' $false)
$dryEnabled=[bool](Get-Field $dry 'local_dry_run' $false)
$mode='UNKNOWN'

if($liveEnabled){
  $mode='LIVE_ARMED'
}elseif($dryEnabled){
  $mode='DRY_RUN'
}elseif($live){
  $mode='LIVE_BRIDGE_DISARMED'
}elseif($dry){
  $mode='DRYRUN_BRIDGE_PRESENT'
}

Write-Host ('Execution mode: '+$mode) -ForegroundColor Cyan
if($live){
  Write-Host ('LIVE max stake: '+[string](Get-Field $live 'max_stake_usdt' '—')+' USDT')
  Write-Host ('LIVE max leverage: '+[string](Get-Field $live 'max_leverage' '—')+'x')
  Write-Host ('LIVE events: '+[string](Get-Field $live 'events' 0))
}
if($dry){
  Write-Host ('DRY-RUN auto: '+[string](Get-Field $dry 'auto_enabled' $false))
  Write-Host ('DRY-RUN events: '+[string](Get-Field $dry 'events' 0))
}

Write-Host '[7/8] Checking analysis agents...'
$ext=Invoke-SafeRest 'http://127.0.0.1:8088/external-market/status' $headers 10
$mt5=Invoke-SafeRest 'http://127.0.0.1:8088/mt5-shadow/status' $headers 10

if($ext){
  $extMode=[string](Get-Field $ext 'mode' 'UNKNOWN')
  $cached=[string](Get-Field $ext 'investing_cached_symbols' (Get-Field $ext 'investing_cache_symbols' 0))
  $macro=[string](Get-Field $ext 'macro_cached' (Get-Field $ext 'macro_state' 'NO_DATA'))
  Write-Host ('External XCheck: '+$extMode+' · investing_cache='+$cached+' · macro='+$macro) -ForegroundColor Green
}else{
  Write-Host '[WARN] External Market Shadow endpoint unavailable.' -ForegroundColor Yellow
}

if($mt5){
  $mt5Mode=[string](Get-Field $mt5 'mode' 'UNKNOWN')
  $mt5TokenPresent=[string](Get-Field $mt5 'token_present' $false)
  $mt5Cache=[string](Get-Field $mt5 'cache_symbols' 0)
  Write-Host ('MT5 Shadow: '+$mt5Mode+' · token='+$mt5TokenPresent+' · cache='+$mt5Cache+' · collector='+$collectorState) -ForegroundColor Green
  if($collectorReason){Write-Host ('MT5 reason: '+$collectorReason) -ForegroundColor Yellow}
}else{
  Write-Host ('[WARN] MT5 Shadow endpoint unavailable · collector='+$collectorState) -ForegroundColor Yellow
}

Write-Host '[8/8] Recent execution events...'
if($live){
  $recent=Invoke-SafeRest 'http://127.0.0.1:8088/freqtrade-live/recent?limit=5' $headers 10
  $items=Get-Field $recent 'items' @()
  if($items -and @($items).Count -gt 0){
    foreach($ev in @($items)){
      $evStatus=[string](Get-Field $ev 'status' '—')
      $evPair=[string](Get-Field $ev 'pair' '—')
      $evSide=[string](Get-Field $ev 'side' '—')
      $evSource=[string](Get-Field $ev 'source' '—')
      Write-Host (' LIVE · '+$evStatus+' · '+$evPair+' · '+$evSide+' · '+$evSource)
    }
  }else{
    Write-Host ' LIVE · no events yet'
  }
}
if($dry){
  Write-Host (' DRY-RUN · events='+[string](Get-Field $dry 'events' 0))
}
if(-not $live -and -not $dry){
  Write-Host ' execution bridge endpoints unavailable'
}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' MYSHKA STACK IS RUNNING ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Mode: '+$mode)
Write-Host ('MT5 collector: '+$collectorState)
if($collectorReason){Write-Host ('MT5 detail: '+$collectorReason)}
Write-Host 'Signals/scan logic: ASTRA'
Write-Host 'Execution: Freqtrade bridge'
Write-Host 'XChecks: Binance + Investing + Macro + MT5 Shadow'
Write-Host 'Forward evaluation: 5m / 10m / 15m'
Write-Host 'Telegram: existing ASTRA configuration'
Write-Host ''

if($mode -eq 'LIVE_ARMED'){
  Write-Host 'REAL-MONEY LIVE IS ARMED. A qualifying ASTRA ENTER may be routed to Freqtrade.' -ForegroundColor Red
}elseif($mode -eq 'DRY_RUN'){
  Write-Host 'DRY-RUN is active. Trades remain simulated.' -ForegroundColor Yellow
}else{
  Write-Host 'LIVE is NOT confirmed. This RUN script did not change execution mode.' -ForegroundColor Yellow
}

if($collectorState -eq 'NO_DATA'){
  Write-Host 'MT5 is optional SHADOW context right now; NO_DATA does not block ASTRA.' -ForegroundColor Yellow
}
