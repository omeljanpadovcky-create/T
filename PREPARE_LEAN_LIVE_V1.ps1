$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - LEAN LIVE PREP V1 ' -ForegroundColor Yellow
Write-Host ' ONE STRATEGY · MINIMAL RUNTIME · LIVE NOT ARMED ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$commit='818b1848f66c77e09c3c8532bf4e36b3a6c261d3'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$commit
$env:COMPOSE_ANSI='never'
$env:BUILDKIT_PROGRESS='plain'

$app=$null
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  $rawText=& docker inspect myshka-astra 2>$null
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -eq 0 -and $rawText){
    $raw=$rawText | ConvertFrom-Json
    if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
      $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
    }
  }
}catch{}

if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback 'api.py')){$app=$fallback}
}
if(-not $app){throw 'ASTRA project folder not found.'}

$api=Join-Path $app 'api.py'
$envFile=Join-Path $app '.env.live-armed'
if(-not (Test-Path $api)){throw 'api.py not found.'}
if(-not (Test-Path $envFile)){throw '.env.live-armed not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-lean-live-prep-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null

foreach($name in @('api.py','.env.live-armed','fasttrack_paper_canary.py','freqtrade_live_bridge.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_lean_live_prep_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

$downloads=@{
  'fasttrack_paper_canary.py'=$root+'/astra_fasttrack_canary/fasttrack_paper_canary.py'
  'freqtrade_live_bridge.py'=$root+'/astra_freqtrade_live_bridge/freqtrade_live_bridge.py'
  'patch_fasttrack_shadow_ctx_v1.py'=$root+'/astra_fasttrack_canary/patch_fasttrack_shadow_ctx_v1.py'
  'patch_lean_runtime_v1.py'=$root+'/astra_lean_runtime/patch_lean_runtime_v1.py'
}

Write-Host '[1/9] Downloading pinned LEAN bundle...'
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri ($downloads[$name]+'?x='+$nonce) -Headers @{'Cache-Control'='no-cache, no-store, max-age=0';'Pragma'='no-cache'} -OutFile (Join-Path $tmp $name) -TimeoutSec 60
}

Write-Host '[2/9] Verifying bundle markers...'
$checks=@{
  'fasttrack_paper_canary.py'=@('ASTRA_FASTTRACK_EXECUTION_MODE','shadow_real_jev','binance_checked')
  'freqtrade_live_bridge.py'=@('ASTRA_LIVE_MAX_OPEN_TRADES','ASTRA_LIVE_MAX_ORDERS_PER_DAY','daily_order_cap_clear')
  'patch_fasttrack_shadow_ctx_v1.py'=@('MYSHKA_FASTTRACK_SHADOW_CTX_V1','fasttrack_shadow_ctx')
  'patch_lean_runtime_v1.py'=@('MYSHKA_LEAN_RUNTIME_V1','fasttrack_canary_observe(results)')
}
foreach($name in $checks.Keys){
  $src=Get-Content (Join-Path $tmp $name) -Raw -Encoding UTF8
  foreach($m in $checks[$name]){
    if($src -notlike ('*'+$m+'*')){throw ('Missing marker '+$m+' in '+$name)}
  }
}
Write-Host '[OK] Bundle markers verified.' -ForegroundColor Green

Write-Host '[3/9] Compiling downloaded Python...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile (Join-Path $tmp 'fasttrack_paper_canary.py') (Join-Path $tmp 'freqtrade_live_bridge.py') (Join-Path $tmp 'patch_fasttrack_shadow_ctx_v1.py') (Join-Path $tmp 'patch_lean_runtime_v1.py')
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'LEAN bundle compile failed. Nothing installed.'}
Write-Host '[OK] Bundle compiles.' -ForegroundColor Green

Write-Host '[4/9] Testing API patches on a copy...'
$dry=Join-Path $tmp 'dryrun'
New-Item -ItemType Directory -Path $dry -Force | Out-Null
Copy-Item $api (Join-Path $dry 'api.py') -Force

$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python (Join-Path $tmp 'patch_fasttrack_shadow_ctx_v1.py') $dry
$rc1=$LASTEXITCODE
& python (Join-Path $tmp 'patch_lean_runtime_v1.py') $dry
$rc2=$LASTEXITCODE
if($rc1 -eq 0 -and $rc2 -eq 0){
  & python -m py_compile (Join-Path $dry 'api.py')
  $rc3=$LASTEXITCODE
}else{$rc3=1}
$ErrorActionPreference=$old
if($rc1 -ne 0 -or $rc2 -ne 0 -or $rc3 -ne 0){
  throw 'LEAN API dry-run patch failed. Local ASTRA unchanged.'
}
Write-Host '[OK] API patches work on copy.' -ForegroundColor Green

function Set-EnvKey {
  param([string[]]$Lines,[string]$Key,[string]$Value)
  $filtered=@($Lines | Where-Object {$_ -notmatch ('^'+[regex]::Escape($Key)+'=')})
  return @($filtered + ($Key+'='+$Value))
}

Write-Host '[5/9] Applying minimal runtime configuration...'
$lines=Get-Content $envFile

# Current execution stays PAPER/DRY_RUN.
$lines=Set-EnvKey $lines 'FREQTRADE__DRY_RUN' 'true'
$lines=Set-EnvKey $lines 'ASTRA_FREQTRADE_DRYRUN_AUTO' 'false'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_CANARY_ENABLED' 'true'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_EXECUTION_MODE' 'DRY_RUN'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_CANARY_STAKE_USDT' '10'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_CANARY_MAX_CONCURRENT' '1'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_CANARY_CLUSTER_SEC' '300'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_CANARY_HOLD_SEC' '900'
$lines=Set-EnvKey $lines 'ASTRA_FASTTRACK_CANARY_REAPER_SEC' '60'

# Legacy heavy research stays off.
$lines=Set-EnvKey $lines 'NEWS_INTELLIGENCE_ENABLED' 'false'

# LIVE backend is PREPARED but explicitly DISARMED.
$lines=Set-EnvKey $lines 'ASTRA_LIVE_EXECUTION' 'false'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_CONFIRM' 'NOT_ARMED'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_KILL_SWITCH' 'true'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_STAKE_USDT' '10'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_LEVERAGE' '1'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_OPEN_TRADES' '1'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_MAX_ORDERS_PER_DAY' '3'
$lines=Set-EnvKey $lines 'ASTRA_LIVE_COOLDOWN_SEC' '300'

$lines | Set-Content $envFile -Encoding ASCII
Write-Host '[OK] Minimal env written.' -ForegroundColor Green

Write-Host '[6/9] Installing LEAN runtime files...'
try{
  Copy-Item (Join-Path $tmp 'fasttrack_paper_canary.py') (Join-Path $app 'fasttrack_paper_canary.py') -Force
  Copy-Item (Join-Path $tmp 'freqtrade_live_bridge.py') (Join-Path $app 'freqtrade_live_bridge.py') -Force

  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python (Join-Path $tmp 'patch_fasttrack_shadow_ctx_v1.py') $app
  $rp1=$LASTEXITCODE
  & python (Join-Path $tmp 'patch_lean_runtime_v1.py') $app
  $rp2=$LASTEXITCODE
  Push-Location $app
  try{
    & python -m py_compile 'api.py' 'fasttrack_paper_canary.py' 'freqtrade_live_bridge.py'
    $rpc=$LASTEXITCODE
  }finally{Pop-Location}
  $ErrorActionPreference=$old

  if($rp1 -ne 0 -or $rp2 -ne 0 -or $rpc -ne 0){throw 'Local LEAN compile failed.'}
}catch{
  foreach($name in @('api.py','.env.live-armed','fasttrack_paper_canary.py','freqtrade_live_bridge.py')){
    $b=Join-Path $backup $name
    if(Test-Path $b){Copy-Item $b (Join-Path $app $name) -Force}
  }
  Write-Host '[ROLLBACK] Previous runtime restored.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] LEAN runtime installed.' -ForegroundColor Green

# Keep a human-readable manifest instead of physically deleting imports/endpoints.
$manifest=@'
MYSHKA / ASTRA - LEAN RUNTIME V1

ACTIVE TRADING PATH
Market Data
-> TECH 3/4 relaxed candidate
-> Binance AGREE
-> economic EDGE/cost check
-> JEV
-> FastTrack execution router
-> Freqtrade DRY_RUN now / LIVE backend later

ACTIVE SAFETY
Kill switch
Whitelist
Same-pair duplicate block
Cooldown
Max open trades = 1
Max LIVE orders/day = 3
Max LIVE stake = 10 USDT
Max LIVE leverage = 1x
Telegram/runtime controls
Execution audit (if installed)

DISABLED FROM SCAN LOOP
Evidence Gate
Adaptive Learner
Counterfactual Shadow
Risk Intelligence Shadow
Hardening Observer
Forward Experiment Lab
News Outcomes
Multi-Horizon Shadow
Binance observer (FastTrack performs xcheck directly)
External Market Shadow/Xcheck
Legacy Live-DryRun observer
Legacy Freqtrade DRYRUN auto observer
Legacy Freqtrade LIVE auto observer

NOTE
Old source files remain only for rollback/forensics.
They are not part of the active trading decision loop.
'@
$manifest | Set-Content (Join-Path $app 'LEAN_RUNTIME_MANIFEST.txt') -Encoding UTF8

Write-Host '[7/9] Rebuilding ASTRA only...'
Push-Location $app
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rr=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rr -ne 0){throw 'ASTRA rebuild failed.'}
}finally{Pop-Location}

Write-Host '[8/9] Health + safety verification...'
$health=$null
$healthMs=$null
for($i=0;$i -lt 35;$i++){
  Start-Sleep -Seconds 2
  try{
    $sw=[Diagnostics.Stopwatch]::StartNew()
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 6
    $sw.Stop()
    $healthMs=$sw.ElapsedMilliseconds
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed.'}

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} | ForEach-Object {$_.Substring($_.IndexOf('=')+1)} | Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$h=@{'X-MYSHKA-TOKEN'=$token}

$canary=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $h -TimeoutSec 10
$live=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-live/status' -Headers $h -TimeoutSec 10

if($canary.execution_mode -ne 'DRY_RUN'){throw 'FastTrack is not in DRY_RUN mode.'}
if($canary.local_dry_run -ne $true){throw 'Local DRY_RUN is not confirmed.'}
if($live.local_live_enabled -eq $true){throw 'LIVE bridge unexpectedly armed.'}
if($live.max_leverage -gt 1){throw 'LIVE leverage cap unsafe.'}
if($live.max_open_trades -ne 1){throw 'LIVE open-trade cap unsafe.'}

Write-Host '[9/9] Runtime snapshot...' -ForegroundColor Cyan
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' myshka-astra
$ErrorActionPreference=$old

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - LEAN LIVE PREP V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Health latency: '+$healthMs+' ms')
Write-Host ('FastTrack backend: '+$canary.execution_mode)
Write-Host ('Freqtrade local DRY_RUN: '+$canary.local_dry_run)
Write-Host ('LIVE bridge armed: '+$live.local_live_enabled)
Write-Host ('LIVE max stake: '+$live.max_stake_usdt+' USDT')
Write-Host ('LIVE max leverage: '+$live.max_leverage+'x')
Write-Host ('LIVE max open trades: '+$live.max_open_trades)
Write-Host ('LIVE max orders/day: '+$live.max_orders_per_day)
Write-Host ('LIVE cooldown: '+$live.cooldown_sec+' sec')
Write-Host ''
Write-Host 'ACTIVE PATH: TECH3 -> BINANCE AGREE -> EDGE -> JEV -> EXECUTOR'
Write-Host 'LEGACY RESEARCH OBSERVERS: OFF'
Write-Host 'OLD DRYRUN/LIVE AUTO ROUTERS: OFF'
Write-Host 'REAL MONEY: OFF'
Write-Host 'KILL SWITCH: ON'
Write-Host ''
Write-Host ('Manifest: '+(Join-Path $app 'LEAN_RUNTIME_MANIFEST.txt'))
Write-Host ('Backup: '+$backup)
