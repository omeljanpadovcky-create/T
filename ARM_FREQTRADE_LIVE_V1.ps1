param(
  [double]$MaxStakeUSDT = 10,
  [double]$MaxLeverage = 1,
  [Parameter(Mandatory=$true)]
  [string]$Confirm
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Red
Write-Host ' MYSHKA / ASTRA - ARM FREQTRADE LIVE V1 ' -ForegroundColor Yellow
Write-Host ' REAL-MONEY EXECUTION ACTIVATION ' -ForegroundColor Red
Write-Host '==========================================================' -ForegroundColor Red

if($Confirm -ne 'REAL_MONEY_CONFIRMED'){
  throw 'HARD STOP: -Confirm must equal REAL_MONEY_CONFIRMED'
}
if($MaxStakeUSDT -le 0){throw 'MaxStakeUSDT must be > 0.'}
if($MaxLeverage -lt 1){throw 'MaxLeverage must be >= 1.'}
if($MaxStakeUSDT -gt 25){throw 'HARD STOP: V1 cap is 25 USDT per trade.'}
if($MaxLeverage -gt 3){throw 'HARD STOP: V1 cap is 3x leverage.'}

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
if(-not (Test-Path '.env.live-armed')){throw '.env.live-armed not found.'}
if(-not (Test-Path 'freqtrade_live_bridge.py')){throw 'freqtrade_live_bridge.py not installed. Run INSTALL_FREQTRADE_LIVE_BRIDGE_V1.ps1 first.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-live-arm-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item '.env.live-armed' (Join-Path $backup '.env.live-armed') -Force
if(Test-Path 'compose.override.yaml'){Copy-Item 'compose.override.yaml' (Join-Path $backup 'compose.override.yaml') -Force}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

function Set-EnvKey {
  param([string[]]$Lines,[string]$Key,[string]$Value)
  $filtered=@($Lines | Where-Object {$_ -notmatch ('^'+[regex]::Escape($Key)+'=')})
  return @($filtered + ($Key+'='+$Value))
}

function Save-EnvLines {
  param([string[]]$Lines)
  $Lines | Set-Content '.env.live-armed' -Encoding ASCII
}

function Restore-DryRun {
  Write-Host '[ROLLBACK] Restoring previous env/compose...' -ForegroundColor Yellow
  Copy-Item (Join-Path $backup '.env.live-armed') '.env.live-armed' -Force
  $oldCompose=Join-Path $backup 'compose.override.yaml'
  if(Test-Path $oldCompose){
    Copy-Item $oldCompose 'compose.override.yaml' -Force
  }
  try {
    docker compose up -d --force-recreate freqtrade astra | Out-Host
  } catch {}
}

function Get-Token {
  $t=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
    Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} |
    Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
  return $t
}

Write-Host '[1/7] PHASE A: switch Freqtrade to LIVE while ASTRA kill-switch stays ON...' -ForegroundColor Yellow
$lines=Get-Content '.env.live-armed'
$lines=Set-EnvKey $lines 'FREQTRADE__DRY_RUN' 'false'
$lines=Set-EnvKey $lines 'FREQTRADE__FORCE_ENTRY_ENABLE' 'true'
$lines=Set-EnvKey $lines 'FREQTRADE__INITIAL_STATE' 'running'
$lines=Set-EnvKey $lines 'ASTRA_FREQTRADE_DRYRUN_AUTO' 'false'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_EXECUTION' 'false'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_CONFIRM' 'NOT_ARMED'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_KILL_SWITCH' 'true'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_STAKE_USDT' ([string]$MaxStakeUSDT)
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_LEVERAGE' ([string]$MaxLeverage)
$lines=Set-EnvKey $lines 'ASTRA_LIVE_COOLDOWN_SEC' '180'
Save-EnvLines $lines

try {
  docker compose up -d --build --force-recreate freqtrade astra | Out-Host
  if($LASTEXITCODE -ne 0){throw 'Docker recreate failed in Phase A.'}
} catch {
  Restore-DryRun
  throw
}

Write-Host '[2/7] Wait for ASTRA + Freqtrade...'
$astraReady=$false
$ftReady=$false
for($i=0;$i -lt 45;$i++){
  Start-Sleep -Seconds 2
  try {
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($h.status -eq 'ok'){$astraReady=$true}
  } catch {}
  try {
    $p=cmd /c 'docker exec myshka-astra python -c "import urllib.request; print(urllib.request.urlopen(''http://freqtrade:8080/api/v1/ping'',timeout=3).status)" 2>nul'
    if($p -match '200'){$ftReady=$true}
  } catch {}
  if($astraReady -and $ftReady){break}
}
if(-not $astraReady -or -not $ftReady){
  Restore-DryRun
  throw 'HARD STOP: ASTRA/Freqtrade did not become ready.'
}
Write-Host '[OK] ASTRA + Freqtrade ready' -ForegroundColor Green

Write-Host '[3/7] Verify REMOTE Freqtrade is truly LIVE...'
$remote = @'
import os,json,base64,urllib.request
base="http://freqtrade:8080"
u=os.getenv("FREQTRADE_USERNAME","")
p=os.getenv("FREQTRADE_PASSWORD","")
def call(path,headers=None,method="GET"):
    req=urllib.request.Request(base+path,headers=headers or {},method=method)
    with urllib.request.urlopen(req,timeout=8) as r:
        body=r.read().decode()
        try:return r.status,json.loads(body)
        except:return r.status,{}
if not u or not p:
    print(json.dumps({"ok":False,"reason":"missing_credentials"}))
    raise SystemExit(0)
basic=base64.b64encode(f"{u}:{p}".encode()).decode()
code,data=call("/api/v1/token/login",{"Authorization":"Basic "+basic},"POST")
tok=data.get("access_token") if isinstance(data,dict) else None
if not tok:
    print(json.dumps({"ok":False,"reason":"auth_failed","http":code}))
    raise SystemExit(0)
h={"Authorization":"Bearer "+tok}
cc,cfg=call("/api/v1/show_config",h)
cw,wl=call("/api/v1/whitelist",h)
ct,count=call("/api/v1/count",h)
print(json.dumps({
  "ok": cc==200 and cfg.get("dry_run") is False,
  "dry_run":cfg.get("dry_run"),
  "trading_mode":cfg.get("trading_mode"),
  "force_entry_enable":cfg.get("force_entry_enable"),
  "whitelist":(wl.get("whitelist") if isinstance(wl,dict) else []),
  "count":count,
  "show_config_http":cc,
  "whitelist_http":cw,
  "count_http":ct
}))
'@ | docker exec -i myshka-astra python -

$rc=$remote | ConvertFrom-Json
if(-not $rc.ok -or $rc.dry_run -ne $false){
  Restore-DryRun
  throw ('HARD STOP: remote Freqtrade did not confirm dry_run=false. '+($remote -join ' '))
}
if(-not $rc.whitelist -or @($rc.whitelist).Count -lt 1){
  Restore-DryRun
  throw 'HARD STOP: Freqtrade whitelist is empty.'
}
Write-Host ('[OK] REMOTE dry_run=False · trading_mode='+$rc.trading_mode) -ForegroundColor Green
Write-Host ('[OK] Whitelist: '+(@($rc.whitelist) -join ', ')) -ForegroundColor Green

Write-Host '[4/7] Verify ASTRA LIVE bridge remains DISARMED during transition...'
$token=Get-Token
if(-not $token){
  Restore-DryRun
  throw 'MYSHKA_BRIDGE_TOKEN not found.'
}
$headers=@{'X-MYSHKA-TOKEN'=$token}
$before=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-live/status' -Headers $headers -TimeoutSec 15
if($before.local_live_enabled -eq $true){
  Restore-DryRun
  throw 'HARD STOP: LIVE bridge unexpectedly armed during Phase A.'
}
Write-Host '[OK] Kill-switch held: LIVE bridge still disarmed' -ForegroundColor Green

Write-Host '[5/7] PHASE B: ARM ASTRA LIVE execution...' -ForegroundColor Red
$lines=Get-Content '.env.live-armed'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_EXECUTION' 'true'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_CONFIRM' 'REAL_MONEY_CONFIRMED'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_KILL_SWITCH' 'false'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_STAKE_USDT' ([string]$MaxStakeUSDT)
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_LEVERAGE' ([string]$MaxLeverage)
Save-EnvLines $lines

try {
  docker compose up -d --build --force-recreate astra | Out-Host
  if($LASTEXITCODE -ne 0){throw 'ASTRA recreate failed in Phase B.'}
} catch {
  Restore-DryRun
  throw
}

$ready=$false
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 2
  try {
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($h.status -eq 'ok' -and $h.freqtrade_live_bridge){$ready=$true;break}
  } catch {}
}
if(-not $ready){
  Restore-DryRun
  throw 'HARD STOP: ASTRA did not return healthy after arming.'
}

Write-Host '[6/7] Final LIVE bridge verification...'
$token=Get-Token
$headers=@{'X-MYSHKA-TOKEN'=$token}
$st=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-live/status' -Headers $headers -TimeoutSec 15

if($st.mode -ne 'FREQTRADE_LIVE_EXECUTION_BRIDGE_V1'){
  Restore-DryRun
  throw ('Unexpected live bridge mode: '+$st.mode)
}
if($st.local_live_enabled -ne $true){
  Restore-DryRun
  throw ('HARD STOP: local live guard is not fully armed. '+($st | ConvertTo-Json -Depth 8))
}

Write-Host '[7/7] ARMED.' -ForegroundColor Red
Write-Host ''
Write-Host '==========================================================' -ForegroundColor Red
Write-Host ' LIVE ARMED - REAL MONEY EXECUTION ENABLED ' -ForegroundColor Red
Write-Host '==========================================================' -ForegroundColor Red
Write-Host ('Max stake per trade: '+$MaxStakeUSDT+' USDT')
Write-Host ('Max leverage: '+$MaxLeverage+'x')
Write-Host 'Cooldown: 180 sec'
Write-Host ('Whitelist: '+(@($rc.whitelist) -join ', '))
Write-Host 'ASTRA gates remain required: ENTER + EDGE + JEV + Evidence + Adaptive'
Write-Host 'Freqtrade guards remain required: whitelist + slot + no duplicate pair + cooldown'
Write-Host ''
Write-Host 'NO order was manually sent by this ARM script.'
Write-Host 'The next qualifying ASTRA signal may be routed to LIVE execution.'
Write-Host ('Backup: '+$backup)
