param(
  [double]$MaxStakeUSDT = 10,
  [Parameter(Mandatory=$true)]
  [string]$Confirm
)

$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$env:COMPOSE_ANSI='never'
$env:BUILDKIT_PROGRESS='plain'

if($Confirm -ne 'REAL_MONEY_CONFIRMED'){throw 'HARD STOP: -Confirm must equal REAL_MONEY_CONFIRMED'}
if($MaxStakeUSDT -le 0 -or $MaxStakeUSDT -gt 10){throw 'HARD STOP: LEAN V1 max stake is 10 USDT.'}

Write-Host '==========================================================' -ForegroundColor Red
Write-Host ' MYSHKA / ASTRA - ARM LEAN LIVE V1 ' -ForegroundColor Yellow
Write-Host ' REAL MONEY · FASTTRACK ONLY ' -ForegroundColor Red
Write-Host '==========================================================' -ForegroundColor Red

$app=$null
try{
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
}catch{}
if(-not $app){throw 'ASTRA project folder not found.'}
Set-Location $app

if(-not (Test-Path '.env.live-armed')){throw '.env.live-armed not found.'}
if(-not (Test-Path 'LEAN_RUNTIME_MANIFEST.txt')){throw 'LEAN runtime not prepared. Run PREPARE_LEAN_LIVE_V1.ps1 first.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-arm-lean-live-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item '.env.live-armed' (Join-Path $backup '.env.live-armed') -Force

function Set-EnvKey {
  param([string[]]$Lines,[string]$Key,[string]$Value)
  $filtered=@($Lines | Where-Object {$_ -notmatch ('^'+[regex]::Escape($Key)+'=')})
  return @($filtered + ($Key+'='+$Value))
}

# Phase A: Freqtrade LIVE, ASTRA still hard-killed.
$lines=Get-Content '.env.live-armed'
$lines=Set-EnvKey $lines 'FREQTRADE__DRY_RUN' 'false'
$lines=Set-EnvKey $lines 'ASTRA_FREQTRADE_DRYRUN_AUTO' 'false'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_EXECUTION_MODE' 'DRY_RUN'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_EXECUTION' 'false'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_CONFIRM' 'NOT_ARMED'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_KILL_SWITCH' 'true'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_STAKE_USDT' ([string]$MaxStakeUSDT)
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_LEVERAGE' '1'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_OPEN_TRADES' '1'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_ORDERS_PER_DAY' '3'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_COOLDOWN_SEC' '300'
$lines | Set-Content '.env.live-armed' -Encoding ASCII

$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker compose --ansi never up -d --build --force-recreate freqtrade astra
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){
  Copy-Item (Join-Path $backup '.env.live-armed') '.env.live-armed' -Force
  throw 'Phase A rebuild failed. Env restored.'
}

$ready=$false
for($i=0;$i -lt 40;$i++){
  Start-Sleep -Seconds 2
  try{
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($h.status -eq 'ok'){$ready=$true;break}
  }catch{}
}
if(-not $ready){
  Copy-Item (Join-Path $backup '.env.live-armed') '.env.live-armed' -Force
  throw 'ASTRA did not become healthy.'
}

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} | ForEach-Object {$_.Substring($_.IndexOf('=')+1)} | Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

# Ensure remote Freqtrade really switched live while ASTRA remains disarmed.
$py=@'
import os,json,base64,urllib.request
base=os.getenv("FREQTRADE_BASE_URL","http://freqtrade:8080").rstrip("/")
u=os.getenv("FREQTRADE_USERNAME",""); p=os.getenv("FREQTRADE_PASSWORD","")
def req(path,method="GET",headers=None):
    r=urllib.request.Request(base+path,method=method,headers=headers or {})
    with urllib.request.urlopen(r,timeout=8) as x:
        b=x.read().decode()
        return x.status,json.loads(b)
basic=base64.b64encode(f"{u}:{p}".encode()).decode()
c,d=req("/api/v1/token/login","POST",{"Authorization":"Basic "+basic})
tok=d.get("access_token")
h={"Authorization":"Bearer "+tok}
cc,cfg=req("/api/v1/show_config",headers=h)
cw,wl=req("/api/v1/whitelist",headers=h)
ct,cnt=req("/api/v1/count",headers=h)
print(json.dumps({"dry_run":cfg.get("dry_run"),"whitelist":wl.get("whitelist",[]),"count":cnt,"ok":cc==200 and cfg.get("dry_run") is False}))
'@
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
$remote=$py | docker exec -i myshka-astra python -
$rr=$LASTEXITCODE
$ErrorActionPreference=$old
if($rr -ne 0){throw 'Remote Freqtrade preflight failed.'}
$rf=$remote | ConvertFrom-Json
if(-not $rf.ok -or $rf.dry_run -ne $false){throw 'HARD STOP: remote Freqtrade did not confirm LIVE.'}
if(-not $rf.whitelist -or @($rf.whitelist).Count -lt 1){throw 'HARD STOP: empty whitelist.'}

$live0=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-live/status' -Headers $headers -TimeoutSec 10
if($live0.local_live_enabled -eq $true){throw 'HARD STOP: live bridge armed before Phase B.'}

# Phase B: select the SAME FastTrack strategy backend and arm bridge.
$lines=Get-Content '.env.live-armed'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_EXECUTION_MODE' 'LIVE'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_EXECUTION' 'true'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_CONFIRM' 'REAL_MONEY_CONFIRMED'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_KILL_SWITCH' 'false'
$lines | Set-Content '.env.live-armed' -Encoding ASCII

$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker compose --ansi never up -d --build --force-recreate astra
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'Phase B ASTRA rebuild failed.'}

Start-Sleep -Seconds 5
$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} | ForEach-Object {$_.Substring($_.IndexOf('=')+1)} | Select-Object -First 1)
$headers=@{'X-MYSHKA-TOKEN'=$token}
$canary=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
$live=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-live/status' -Headers $headers -TimeoutSec 10

if($canary.execution_mode -ne 'LIVE'){throw 'FastTrack backend did not switch to LIVE.'}
if($live.local_live_enabled -ne $true){throw 'Live bridge guard is not armed.'}
if($live.max_leverage -ne 1){throw 'Leverage cap mismatch.'}
if($live.max_open_trades -ne 1){throw 'Open-trade cap mismatch.'}
if($live.max_orders_per_day -ne 3){throw 'Daily-order cap mismatch.'}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Red
Write-Host ' LEAN LIVE ARMED - REAL MONEY EXECUTION ENABLED ' -ForegroundColor Red
Write-Host '==========================================================' -ForegroundColor Red
Write-Host ('FastTrack: '+$canary.execution_mode)
Write-Host ('Max stake: '+$live.max_stake_usdt+' USDT')
Write-Host 'Leverage: 1x'
Write-Host 'Max open trades: 1'
Write-Host 'Max entries/day: 3'
Write-Host 'Cooldown: 300 sec'
Write-Host 'Only active signal path: TECH3 -> BINANCE AGREE -> EDGE -> JEV'
Write-Host ('Backup: '+$backup)
