$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$env:COMPOSE_ANSI='never'
$env:BUILDKIT_PROGRESS='plain'

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FINAL EXIT SAFETY PREP V1 ' -ForegroundColor Yellow
Write-Host ' BYBIT FUTURES · ON-EXCHANGE STOP · STILL DRY_RUN ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=$null
try{
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
}catch{}
if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback '.env.live-armed')){$app=$fallback}
}
if(-not $app){throw 'ASTRA project folder not found.'}

Set-Location $app
if(-not (Test-Path '.env.live-armed')){throw '.env.live-armed not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-final-exit-safety-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item '.env.live-armed' (Join-Path $backup '.env.live-armed') -Force

function Set-EnvKey {
  param([string[]]$Lines,[string]$Key,[string]$Value)
  $filtered=@($Lines | Where-Object {$_ -notmatch ('^'+[regex]::Escape($Key)+'=')})
  return @($filtered + ($Key+'='+$Value))
}

Write-Host '[1/5] Writing Freqtrade safety overrides...'
$lines=Get-Content '.env.live-armed'

# Keep paper execution while validating final LIVE-shaped config.
$lines=Set-EnvKey $lines 'FREQTRADE__DRY_RUN' 'true'
$lines=Set-EnvKey $lines 'FREQTRADE__MAX_OPEN_TRADES' '1'

# Full explicit order_types surface via env overrides.
$lines=Set-EnvKey $lines 'FREQTRADE__ORDER_TYPES__ENTRY' 'limit'
$lines=Set-EnvKey $lines 'FREQTRADE__ORDER_TYPES__EXIT' 'limit'
$lines=Set-EnvKey $lines 'FREQTRADE__ORDER_TYPES__EMERGENCY_EXIT' 'market'
$lines=Set-EnvKey $lines 'FREQTRADE__ORDER_TYPES__FORCE_ENTRY' 'market'
$lines=Set-EnvKey $lines 'FREQTRADE__ORDER_TYPES__FORCE_EXIT' 'market'
$lines=Set-EnvKey $lines 'FREQTRADE__ORDER_TYPES__STOPLOSS' 'market'
$lines=Set-EnvKey $lines 'FREQTRADE__ORDER_TYPES__STOPLOSS_ON_EXCHANGE' 'true'
$lines=Set-EnvKey $lines 'FREQTRADE__ORDER_TYPES__STOPLOSS_ON_EXCHANGE_INTERVAL' '60'

# LEAN safety remains disarmed.
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_EXECUTION_MODE' 'DRY_RUN'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_EXECUTION' 'false'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_CONFIRM' 'NOT_ARMED'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_KILL_SWITCH' 'true'

$lines | Set-Content '.env.live-armed' -Encoding ASCII
Write-Host '[OK] Env overrides written.' -ForegroundColor Green

Write-Host '[2/5] Recreating Freqtrade + ASTRA...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker compose --ansi never up -d --build --force-recreate freqtrade astra
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){
  Copy-Item (Join-Path $backup '.env.live-armed') '.env.live-armed' -Force
  throw 'Docker recreate failed. Previous env restored.'
}

Write-Host '[3/5] Waiting for ASTRA + Freqtrade...'
$astraReady=$false
$ftReady=$false
for($i=0;$i -lt 60;$i++){
  Start-Sleep -Seconds 2

  try{
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($h.status -eq 'ok'){$astraReady=$true}
  }catch{}

  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  try{
    $ping='import urllib.request; print(urllib.request.urlopen("http://freqtrade:8080/api/v1/ping",timeout=3).status)'
    $pong=$ping | docker exec -i myshka-astra python - 2>&1
    $prc=$LASTEXITCODE
    if($prc -eq 0 -and (($pong -join [Environment]::NewLine) -match '200')){$ftReady=$true}
  }catch{}
  $ErrorActionPreference=$old

  if($astraReady -and $ftReady){break}
}
if(-not $astraReady){throw 'ASTRA did not become healthy.'}
if(-not $ftReady){throw 'Freqtrade API did not become ready.'}
Write-Host '[OK] ASTRA + Freqtrade API ready.' -ForegroundColor Green

Write-Host '[4/5] Reading effective Freqtrade config...'
$py=@'
import os,json,base64,urllib.request
base=os.getenv("FREQTRADE_BASE_URL","http://freqtrade:8080").rstrip("/")
u=os.getenv("FREQTRADE_USERNAME","")
p=os.getenv("FREQTRADE_PASSWORD","")
def req(path,method="GET",headers=None):
    q=urllib.request.Request(base+path,method=method,headers=headers or {})
    with urllib.request.urlopen(q,timeout=8) as x:
        b=x.read().decode()
        try:return x.status,json.loads(b)
        except:return x.status,{}
basic=base64.b64encode(f"{u}:{p}".encode()).decode()
c,d=req("/api/v1/token/login","POST",{"Authorization":"Basic "+basic})
tok=d.get("access_token")
if not tok:
    print(json.dumps({"ok":False,"reason":"auth_failed","http":c}))
    raise SystemExit(0)
cc,cfg=req("/api/v1/show_config",headers={"Authorization":"Bearer "+tok})
print(json.dumps({
  "ok":cc==200,
  "dry_run":cfg.get("dry_run"),
  "trading_mode":cfg.get("trading_mode"),
  "margin_mode":cfg.get("margin_mode"),
  "max_open_trades":cfg.get("max_open_trades"),
  "stoploss":cfg.get("stoploss"),
  "minimal_roi":cfg.get("minimal_roi"),
  "order_types":cfg.get("order_types"),
  "force_entry_enable":cfg.get("force_entry_enable"),
},ensure_ascii=False))
'@

$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
$rawCfg=$py | docker exec -i myshka-astra python -
$rr=$LASTEXITCODE
$ErrorActionPreference=$old
if($rr -ne 0){throw 'Could not read Freqtrade config.'}
$cfg=$rawCfg | ConvertFrom-Json

if(-not $cfg.ok){throw ('Freqtrade config API failed: '+($rawCfg -join ' '))}
if($cfg.dry_run -ne $true){throw 'HARD STOP: Freqtrade is not DRY_RUN during prep.'}
if([int]$cfg.max_open_trades -ne 1){throw 'HARD STOP: max_open_trades is not 1.'}
if($cfg.order_types.stoploss_on_exchange -ne $true){throw 'HARD STOP: stoploss_on_exchange is not TRUE.'}
if([string]$cfg.order_types.stoploss -ne 'market'){throw 'HARD STOP: stoploss order type is not market.'}
if([string]$cfg.order_types.emergency_exit -ne 'market'){throw 'HARD STOP: emergency_exit is not market.'}
if([string]$cfg.trading_mode -ne 'futures'){throw 'HARD STOP: trading_mode is not futures.'}
if([string]$cfg.margin_mode -ne 'isolated'){throw 'HARD STOP: margin_mode is not isolated.'}

Write-Host '[5/5] Verifying LEAN bridge remains disarmed...'
$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} | ForEach-Object {$_.Substring($_.IndexOf('=')+1)} | Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}
$canary=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
$live=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-live/status' -Headers $headers -TimeoutSec 10

if($canary.execution_mode -ne 'DRY_RUN'){throw 'FastTrack is not DRY_RUN.'}
if($live.local_live_enabled -eq $true){throw 'LIVE bridge unexpectedly armed.'}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - FINAL EXIT SAFETY PREP V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('dry_run: '+$cfg.dry_run)
Write-Host ('trading_mode: '+$cfg.trading_mode)
Write-Host ('margin_mode: '+$cfg.margin_mode)
Write-Host ('max_open_trades: '+$cfg.max_open_trades)
Write-Host ('stoploss: '+$cfg.stoploss)
Write-Host ('minimal_roi: '+(($cfg.minimal_roi | ConvertTo-Json -Compress)))
Write-Host ('stoploss_on_exchange: '+$cfg.order_types.stoploss_on_exchange)
Write-Host ('stoploss order type: '+$cfg.order_types.stoploss)
Write-Host ('emergency_exit: '+$cfg.order_types.emergency_exit)
Write-Host ('FastTrack backend: '+$canary.execution_mode)
Write-Host ('LIVE bridge armed: '+$live.local_live_enabled)
Write-Host 'REAL MONEY: OFF'
Write-Host 'KILL SWITCH: ON'
Write-Host ('Backup: '+$backup)
