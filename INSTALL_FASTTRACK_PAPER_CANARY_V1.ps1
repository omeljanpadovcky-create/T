$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FASTTRACK PAPER CANARY V1 ' -ForegroundColor Yellow
Write-Host ' TECH 3/4 + JEV APPROVE + BINANCE AGREE -> FREQTRADE DRY_RUN ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='c1b9d04481cd785ffd5195be741375297d269cd1'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$bundleCommit
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

if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){
  throw 'ASTRA project folder not found.'
}
if(-not (Test-Path (Join-Path $app '.env.live-armed'))){
  throw '.env.live-armed not found.'
}
if(-not (Test-Path (Join-Path $app 'live_dry_run.py'))){
  throw 'live_dry_run.py not found.'
}

Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

Write-Host '[0/9] HARD PRECHECK: current Freqtrade must be DRY_RUN...'
$preflight = @'
import os,json,base64,urllib.request
base="http://freqtrade:8080"
u=os.getenv("FREQTRADE_USERNAME","")
p=os.getenv("FREQTRADE_PASSWORD","")
def call(path,headers=None,method="GET"):
    r=urllib.request.Request(base+path,headers=headers or {},method=method)
    try:
        with urllib.request.urlopen(r,timeout=8) as x:
            body=x.read().decode()
            try:data=json.loads(body)
            except:data={}
            return x.status,data
    except Exception as e:
        return 0,{"error":f"{type(e).__name__}: {e}"}
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
print(json.dumps({
    "ok": cc==200 and cfg.get("dry_run") is True,
    "http":cc,
    "dry_run":cfg.get("dry_run"),
    "trading_mode":cfg.get("trading_mode"),
    "force_entry_enable":cfg.get("force_entry_enable")
}))
'@ | docker exec -i myshka-astra python -

$pre=$preflight | ConvertFrom-Json
if(-not $pre.ok -or $pre.dry_run -ne $true){
  throw ('HARD STOP: Freqtrade does not confirm dry_run=true. '+($preflight -join ' '))
}
Write-Host ('[OK] Remote Freqtrade dry_run=True · mode='+$pre.trading_mode) -ForegroundColor Green

$envLines=Get-Content (Join-Path $app '.env.live-armed')
$dryLine=$envLines | Where-Object { $_ -match '^FREQTRADE__DRY_RUN=' } | Select-Object -First 1
if($dryLine -and $dryLine -notmatch '=true$'){
  throw ('HARD STOP: local .env does not say FREQTRADE__DRY_RUN=true: '+$dryLine)
}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-fasttrack-paper-canary-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @(
  'api.py',
  'freqtrade_dryrun_bridge.py',
  'execution_slippage_audit.py',
  'fasttrack_paper_canary.py',
  '.env.live-armed'
)){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_fasttrack_paper_canary_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$files=@{
  'fasttrack_paper_canary.py'=$root+'/astra_fasttrack_canary/fasttrack_paper_canary.py'
  'patch_fasttrack_paper_canary.py'=$root+'/astra_fasttrack_canary/patch_fasttrack_paper_canary.py'
  'selftest_fasttrack_paper_canary.py'=$root+'/astra_fasttrack_canary/selftest_fasttrack_paper_canary.py'
  'freqtrade_dryrun_bridge.py'=$root+'/astra_freqtrade_dryrun_bridge/freqtrade_dryrun_bridge.py'
  'execution_slippage_audit.py'=$root+'/astra_execution_audit/execution_slippage_audit.py'
}

Write-Host '[1/9] Downloading pinned canary bundle...'
foreach($name in $files.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri $files[$name] -OutFile (Join-Path $tmp $name) -TimeoutSec 60
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/9] Static safety checks...'
$canarySrc=Get-Content (Join-Path $tmp 'fasttrack_paper_canary.py') -Raw -Encoding UTF8
foreach($marker in @(
  'FASTTRACK_PAPER_CANARY_V1',
  'real_money_execution":False',
  'TECH 3/4 + JEV APPROVE + Binance AGREE',
  'ASTRA_FASTTRACK_CANARY_STAKE_USDT',
  'ASTRA_FASTTRACK_CANARY_MAX_CONCURRENT',
  '/api/v1/forceexit'
)){
  if($canarySrc -notlike ('*'+$marker+'*')){throw ('Missing canary safety marker: '+$marker)}
}
if($canarySrc -match 'FREQTRADE__DRY_RUN\s*=\s*false'){throw 'Unsafe dry_run=false marker found.'}
Write-Host '[OK] PAPER-only safety markers present.' -ForegroundColor Green

Write-Host '[3/9] Compile bundle...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
foreach($name in $files.Keys){
  & python -m py_compile (Join-Path $tmp $name)
  if($LASTEXITCODE -ne 0){
    $ErrorActionPreference=$old
    throw ('Compile failed: '+$name)
  }
}
$ErrorActionPreference=$old
Write-Host '[OK] Python compile passed.' -ForegroundColor Green

Write-Host '[4/9] Synthetic canary self-test...'
$pkg=Join-Path $tmp 'canarypkg'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $pkg '__init__.py') -Force | Out-Null
Copy-Item (Join-Path $tmp 'fasttrack_paper_canary.py') (Join-Path $pkg 'fasttrack_paper_canary.py') -Force
Copy-Item (Join-Path $tmp 'freqtrade_dryrun_bridge.py') (Join-Path $pkg 'freqtrade_dryrun_bridge.py') -Force
Copy-Item (Join-Path $tmp 'execution_slippage_audit.py') (Join-Path $pkg 'execution_slippage_audit.py') -Force
Copy-Item (Join-Path $app 'live_dry_run.py') (Join-Path $pkg 'live_dry_run.py') -Force
Copy-Item (Join-Path $tmp 'selftest_fasttrack_paper_canary.py') (Join-Path $pkg 'selftest_fasttrack_paper_canary.py') -Force

Push-Location $tmp
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python -m canarypkg.selftest_fasttrack_paper_canary
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){throw 'FastTrack canary self-test failed.'}
}finally{Pop-Location}
Write-Host '[OK] Synthetic gate/dedupe/sizing test passed.' -ForegroundColor Green

Write-Host '[5/9] Configure PAPER canary defaults...'
$envPath=Join-Path $app '.env.live-armed'
$envLines=Get-Content $envPath
$envLines=$envLines | Where-Object {
  $_ -notmatch '^ASTRA_FASTTRACK_CANARY_ENABLED=' -and
  $_ -notmatch '^ASTRA_FASTTRACK_CANARY_STAKE_USDT=' -and
  $_ -notmatch '^ASTRA_FASTTRACK_CANARY_MAX_CONCURRENT=' -and
  $_ -notmatch '^ASTRA_FASTTRACK_CANARY_HOLD_SEC=' -and
  $_ -notmatch '^ASTRA_FASTTRACK_CANARY_CLUSTER_SEC=' -and
  $_ -notmatch '^ASTRA_SLIPPAGE_ALERT_BPS=' -and
  $_ -notmatch '^ASTRA_SLIPPAGE_ALERT_COOLDOWN_SEC='
}
$envLines += 'ASTRA_FASTTRACK_CANARY_ENABLED=true'
$envLines += 'ASTRA_FASTTRACK_CANARY_STAKE_USDT=10'
$envLines += 'ASTRA_FASTTRACK_CANARY_MAX_CONCURRENT=1'
$envLines += 'ASTRA_FASTTRACK_CANARY_HOLD_SEC=900'
$envLines += 'ASTRA_FASTTRACK_CANARY_CLUSTER_SEC=300'
$envLines += 'ASTRA_SLIPPAGE_ALERT_BPS=20'
$envLines += 'ASTRA_SLIPPAGE_ALERT_COOLDOWN_SEC=60'
$envLines | Set-Content $envPath -Encoding ASCII
Write-Host '[OK] Canary = 10 USDT paper · 1x · max 1 · 15m max hold · 5m dedupe.' -ForegroundColor Green

Write-Host '[6/9] Install modules + patch API...'
try{
  Copy-Item (Join-Path $tmp 'fasttrack_paper_canary.py') (Join-Path $app 'fasttrack_paper_canary.py') -Force
  Copy-Item (Join-Path $tmp 'freqtrade_dryrun_bridge.py') (Join-Path $app 'freqtrade_dryrun_bridge.py') -Force
  Copy-Item (Join-Path $tmp 'execution_slippage_audit.py') (Join-Path $app 'execution_slippage_audit.py') -Force

  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python (Join-Path $tmp 'patch_fasttrack_paper_canary.py') $app
  $patchRc=$LASTEXITCODE
  if($patchRc -eq 0){
    Push-Location $app
    try{
      & python -m py_compile 'api.py' 'fasttrack_paper_canary.py' 'freqtrade_dryrun_bridge.py' 'execution_slippage_audit.py'
      $compileRc=$LASTEXITCODE
    }finally{Pop-Location}
  }else{$compileRc=1}
  $ErrorActionPreference=$old
  if($patchRc -ne 0 -or $compileRc -ne 0){throw 'Patch/final compile failed.'}
}catch{
  foreach($name in @('api.py','freqtrade_dryrun_bridge.py','execution_slippage_audit.py','fasttrack_paper_canary.py','.env.live-armed')){
    $b=Join-Path $backup $name
    $dst=Join-Path $app $name
    if(Test-Path $b){Copy-Item $b $dst -Force}
    elseif($name -eq 'fasttrack_paper_canary.py' -and (Test-Path $dst)){Remove-Item $dst -Force}
  }
  Write-Host '[ROLLBACK] Previous files restored.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Canary modules installed.' -ForegroundColor Green

Write-Host '[7/9] Rebuild ASTRA only...'
Push-Location $app
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){throw 'ASTRA rebuild failed.'}
}finally{Pop-Location}

Write-Host '[8/9] Health + endpoint verification...'
$health=$null
for($i=0;$i -lt 35;$i++){
  Start-Sleep -Seconds 2
  try{
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 6
    if($health.status -eq 'ok' -and $health.fasttrack_paper_canary){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed.'}
if(-not $health.fasttrack_paper_canary){throw 'Canary missing from /health.'}

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  ForEach-Object { $_.Substring($_.IndexOf('=')+1) } |
  Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

$st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
if($st.mode -ne 'FASTTRACK_PAPER_CANARY_V1'){throw ('Unexpected canary mode: '+$st.mode)}
if($st.local_dry_run -ne $true){throw 'HARD STOP: canary local dry-run not true.'}
if($st.real_money_execution -ne $false){throw 'HARD STOP: unsafe canary live flag.'}

Write-Host ('[OK] Canary endpoint: '+$st.mode) -ForegroundColor Green
Write-Host ('[OK] Filter: '+$st.filter) -ForegroundColor Green
Write-Host ('[OK] Stake: '+$st.stake_usdt+' USDT · leverage '+$st.leverage+'x · max concurrent '+$st.max_concurrent) -ForegroundColor Green

Write-Host '[9/9] Re-confirm remote Freqtrade DRY_RUN after install...'
$remote = @'
import os,json,base64,urllib.request
base="http://freqtrade:8080"
u=os.getenv("FREQTRADE_USERNAME","")
p=os.getenv("FREQTRADE_PASSWORD","")
basic=base64.b64encode(f"{u}:{p}".encode()).decode()
r=urllib.request.Request(base+"/api/v1/token/login",headers={"Authorization":"Basic "+basic},method="POST")
with urllib.request.urlopen(r,timeout=8) as x:
    tok=json.loads(x.read().decode())["access_token"]
r=urllib.request.Request(base+"/api/v1/show_config",headers={"Authorization":"Bearer "+tok})
with urllib.request.urlopen(r,timeout=8) as x:
    cfg=json.loads(x.read().decode())
print(json.dumps({"dry_run":cfg.get("dry_run"),"trading_mode":cfg.get("trading_mode")}))
'@ | docker exec -i myshka-astra python -

$remoteObj=$remote | ConvertFrom-Json
if($remoteObj.dry_run -ne $true){throw 'HARD STOP: remote Freqtrade dry_run changed unexpectedly.'}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - FASTTRACK PAPER CANARY V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'Filter: TECH 3/4 + JEV APPROVE + Binance AGREE'
Write-Host 'Execution: Freqtrade DRY_RUN only'
Write-Host 'Stake: 10 USDT'
Write-Host 'Leverage: 1x'
Write-Host 'Max concurrent canary: 1'
Write-Host 'Duplicate lock: pair + side + 5m'
Write-Host 'Max hold: 15m, then DRY_RUN forceexit'
Write-Host 'Slippage audit: enabled'
Write-Host 'Telegram slippage alert: >=20 bps, 60s cooldown'
Write-Host 'Production EDGE/action/reason changed: NO'
Write-Host 'LIVE armed: NO'
Write-Host 'Real-money execution: FALSE'
Write-Host ('Backup: '+$backup)
