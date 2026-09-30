$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FREQTRADE DRY-RUN EXECUTION BRIDGE V1 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='15919dbbd38740e3790d4f134a99ac6889cc6eb9'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$bundleCommit

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
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){
  throw 'ASTRA project folder not found.'
}

Set-Location $app
Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

& python -m py_compile (Join-Path $app 'api.py')
if($LASTEXITCODE -ne 0){throw 'Current api.py invalid. Nothing modified.'}

if(-not (Test-Path '.env.live-armed')){throw '.env.live-armed not found.'}
if(-not (Test-Path 'compose.override.yaml')){throw 'compose.override.yaml not found.'}
if(-not (Test-Path 'live_dry_run.py')){throw 'live_dry_run.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-freqtrade-dryrun-bridge-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null

foreach($name in @('api.py','freqtrade_dryrun_bridge.py','.env.live-armed','compose.override.yaml')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

Write-Host '[0/11] Verify CURRENT Freqtrade is DRY-RUN...'

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
ct,count=call("/api/v1/count",h)
cw,wl=call("/api/v1/whitelist",h)
print(json.dumps({
    "ok": cc==200 and cfg.get("dry_run") is True,
    "show_config_http":cc,
    "dry_run":cfg.get("dry_run"),
    "trading_mode":cfg.get("trading_mode"),
    "count_http":ct,
    "count":count,
    "whitelist_http":cw,
    "whitelist":(wl.get("whitelist") if isinstance(wl,dict) else [])
}))
'@ | docker exec -i myshka-astra python -

$pre = $preflight | ConvertFrom-Json
if(-not $pre.ok -or $pre.dry_run -ne $true){
  throw ('HARD STOP: current Freqtrade does not confirm dry_run=true. Preflight='+($preflight -join ' '))
}
Write-Host ('[OK] Remote Freqtrade dry_run=True · mode='+$pre.trading_mode) -ForegroundColor Green
Write-Host ('[OK] Whitelist: '+(($pre.whitelist | ForEach-Object {[string]$_}) -join ', ')) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_freqtrade_dryrun_bridge_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

function Get-PinnedRawFile {
  param([string]$RepoPath,[string]$OutFile)
  $nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  $uri=$root+'/'+$RepoPath+'?x='+$nonce
  Invoke-WebRequest -UseBasicParsing -Uri $uri -Headers @{
    'User-Agent'='MYSHKA-ASTRA-FreqtradeDryRunBridge'
    'Cache-Control'='no-cache, no-store, max-age=0'
    'Pragma'='no-cache'
  } -OutFile $OutFile -TimeoutSec 60
}

Write-Host '[1/11] Download pinned bridge bundle...'
Get-PinnedRawFile 'astra_freqtrade_dryrun_bridge/freqtrade_dryrun_bridge.py' (Join-Path $tmp 'freqtrade_dryrun_bridge.py')
Get-PinnedRawFile 'astra_freqtrade_dryrun_bridge/selftest_freqtrade_dryrun_bridge.py' (Join-Path $tmp 'selftest_freqtrade_dryrun_bridge.py')
Get-PinnedRawFile 'astra_freqtrade_dryrun_bridge/patch_freqtrade_dryrun_bridge.py' (Join-Path $tmp 'patch_freqtrade_dryrun_bridge.py')

Write-Host '[2/11] Static safety checks...'
$bridgeSrc=Get-Content (Join-Path $tmp 'freqtrade_dryrun_bridge.py') -Raw -Encoding UTF8
foreach($m in @('FREQTRADE_DRYRUN_EXECUTION_BRIDGE_V1','remote_dry_run_true','local_dry_run_true','real_money_execution','/api/v1/forceenter')){
  if($bridgeSrc -notlike ('*'+$m+'*')){throw ('Missing bridge marker: '+$m)}
}
Write-Host '[OK] DRY-RUN hard-block markers present' -ForegroundColor Green

Write-Host '[3/11] Compile + synthetic self-test...'
$compileFiles=@(
  (Join-Path $tmp 'freqtrade_dryrun_bridge.py'),
  (Join-Path $tmp 'selftest_freqtrade_dryrun_bridge.py'),
  (Join-Path $tmp 'patch_freqtrade_dryrun_bridge.py')
)
& python -m py_compile @compileFiles
if($LASTEXITCODE -ne 0){throw 'Bridge bundle compile failed.'}

$pkg=Join-Path $tmp 'bridgepkg'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $pkg '__init__.py') -Force | Out-Null
Copy-Item (Join-Path $tmp 'freqtrade_dryrun_bridge.py') (Join-Path $pkg 'freqtrade_dryrun_bridge.py') -Force
Copy-Item (Join-Path $tmp 'selftest_freqtrade_dryrun_bridge.py') (Join-Path $pkg 'selftest_freqtrade_dryrun_bridge.py') -Force
Copy-Item (Join-Path $app 'live_dry_run.py') (Join-Path $pkg 'live_dry_run.py') -Force

Push-Location $tmp
try {
  & python -m bridgepkg.selftest_freqtrade_dryrun_bridge
  if($LASTEXITCODE -ne 0){throw 'Bridge self-test failed.'}
} finally {Pop-Location}

Write-Host '[4/11] Configure DRY-RUN force-entry + bridge...'
$envLines=Get-Content '.env.live-armed'
$envLines=$envLines | Where-Object {
  $_ -notmatch '^FREQTRADE__DRY_RUN=' -and
  $_ -notmatch '^FREQTRADE__FORCE_ENTRY_ENABLE=' -and
  $_ -notmatch '^FREQTRADE__INITIAL_STATE=' -and
  $_ -notmatch '^ASTRA_FREQTRADE_DRYRUN_AUTO=' -and
  $_ -notmatch '^ASTRA_FREQTRADE_DRYRUN_COOLDOWN_SEC=' -and
  $_ -notmatch '^ASTRA_FREQTRADE_DRYRUN_MAX_STAKE_USDT=' -and
  $_ -notmatch '^ASTRA_FREQTRADE_DRYRUN_MAX_LEVERAGE='
}
$envLines += 'FREQTRADE__DRY_RUN=true'
$envLines += 'FREQTRADE__FORCE_ENTRY_ENABLE=true'
$envLines += 'FREQTRADE__INITIAL_STATE=running'
$envLines += 'ASTRA_FREQTRADE_DRYRUN_AUTO=true'
$envLines += 'ASTRA_FREQTRADE_DRYRUN_COOLDOWN_SEC=180'
$envLines += 'ASTRA_FREQTRADE_DRYRUN_MAX_STAKE_USDT=25'
$envLines += 'ASTRA_FREQTRADE_DRYRUN_MAX_LEVERAGE=3'
$envLines | Set-Content '.env.live-armed' -Encoding ASCII

@"
services:
  freqtrade:
    env_file:
      - .env.live-armed
    command:
      - trade
      - --config
      - /freqtrade/user_data/config.json
      - --strategy
      - AstraExecutionBridgeStrategy

  astra:
    env_file:
      - .env.live-armed
"@ | Set-Content 'compose.override.yaml' -Encoding UTF8

Write-Host '[OK] dry_run=True · force_entry_enable=True (DRY-RUN only)' -ForegroundColor Green

Write-Host '[5/11] Install bridge module + patch API...'
Copy-Item (Join-Path $tmp 'freqtrade_dryrun_bridge.py') (Join-Path $app 'freqtrade_dryrun_bridge.py') -Force

try {
  & python (Join-Path $tmp 'patch_freqtrade_dryrun_bridge.py') $app
  if($LASTEXITCODE -ne 0){throw 'API patch failed.'}

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'freqtrade_dryrun_bridge.py' 'live_dry_run.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  foreach($name in @('api.py','freqtrade_dryrun_bridge.py','.env.live-armed','compose.override.yaml')){
    $b=Join-Path $backup $name
    $dst=Join-Path $app $name
    if(Test-Path $b){Copy-Item $b $dst -Force}
  }
  throw
}

Write-Host '[6/11] Rebuild/recreate Freqtrade + ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate freqtrade astra
  if($LASTEXITCODE -ne 0){throw 'Docker recreate failed.'}
} finally {Pop-Location}

Write-Host '[7/11] Wait for ASTRA + Freqtrade...'
$astraReady=$false
$ftReady=$false
for($i=0;$i -lt 45;$i++){
  Start-Sleep -Seconds 2
  try{
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($h.status -eq 'ok'){$astraReady=$true}
  }catch{}
  try{
    $p=cmd /c 'docker exec myshka-astra python -c "import urllib.request; print(urllib.request.urlopen(''http://freqtrade:8080/api/v1/ping'',timeout=3).status)" 2>nul'
    if($p -match '200'){$ftReady=$true}
  }catch{}
  if($astraReady -and $ftReady){break}
}
if(-not $astraReady){throw 'ASTRA did not become ready.'}
if(-not $ftReady){throw 'Freqtrade did not become ready.'}
Write-Host '[OK] ASTRA + Freqtrade ready' -ForegroundColor Green

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

Write-Host '[8/11] Verify bridge status...'
$st=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-dryrun/status' -Headers $headers -TimeoutSec 15
if($st.mode -ne 'FREQTRADE_DRYRUN_EXECUTION_BRIDGE_V1'){throw ('Unexpected bridge mode: '+$st.mode)}
if($st.local_dry_run -ne $true){throw 'HARD STOP: bridge local dry-run is not true.'}
if($st.real_money_execution -ne $false){throw 'HARD STOP: unsafe real_money_execution flag.'}
Write-Host ('[OK] Bridge: '+$st.mode+' · local dry-run '+$st.local_dry_run) -ForegroundColor Green

Write-Host '[9/11] Re-confirm REMOTE dry_run=True...'
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
print(json.dumps({"dry_run":cfg.get("dry_run"),"force_entry_enable":cfg.get("force_entry_enable"),"trading_mode":cfg.get("trading_mode")}))
'@ | docker exec -i myshka-astra python -

$rc=$remote | ConvertFrom-Json
if($rc.dry_run -ne $true){throw 'HARD STOP: remote Freqtrade no longer confirms dry_run=True.'}
Write-Host ('[OK] Remote dry_run=True · trading_mode='+$rc.trading_mode) -ForegroundColor Green

Write-Host '[10/11] FULL ROUTE SMOKE: ASTRA -> Freqtrade -> simulated forceenter...'
$pair='BTC/USDT:USDT'
$side='long'
$uri='http://127.0.0.1:8088/freqtrade-dryrun/smoke?pair='+[uri]::EscapeDataString($pair)+'&side='+$side+'&confirm=DRYRUN&stake_usdt=10&leverage=1'
$smoke=Invoke-RestMethod $uri -Method Post -Headers $headers -TimeoutSec 30

Write-Host ('Smoke status: '+$smoke.status)
Write-Host ('HTTP status: '+$smoke.http_status)
Write-Host ('Pair: '+$smoke.pair+' · side '+$smoke.side)
Write-Host ('Local dry-run confirmed: '+$smoke.dry_run_confirmed_local)
Write-Host ('Remote dry-run confirmed: '+$smoke.dry_run_confirmed_remote)
Write-Host ('Real-money execution: '+$smoke.real_money_execution)

if($smoke.status -ne 'sent'){throw ('Smoke forceenter not accepted: '+($smoke | ConvertTo-Json -Depth 8))}
if($smoke.dry_run_confirmed_remote -ne $true){throw 'Smoke did not confirm remote dry-run.'}
if($smoke.real_money_execution -ne $false){throw 'Unsafe smoke flag.'}

Write-Host '[11/11] Verify simulated trade appears in Freqtrade...'
Start-Sleep -Seconds 3
$verify = @'
import os,json,base64,urllib.request
base="http://freqtrade:8080"
u=os.getenv("FREQTRADE_USERNAME","")
p=os.getenv("FREQTRADE_PASSWORD","")
basic=base64.b64encode(f"{u}:{p}".encode()).decode()
r=urllib.request.Request(base+"/api/v1/token/login",headers={"Authorization":"Basic "+basic},method="POST")
with urllib.request.urlopen(r,timeout=8) as x:
    tok=json.loads(x.read().decode())["access_token"]
h={"Authorization":"Bearer "+tok}
for ep in ["/api/v1/count","/api/v1/status"]:
    r=urllib.request.Request(base+ep,headers=h)
    with urllib.request.urlopen(r,timeout=8) as x:
        print(ep, x.status, x.read().decode())
'@ | docker exec -i myshka-astra python -

Write-Host $verify

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - ASTRA -> FREQTRADE DRY-RUN ROUTE V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'ASTRA gated observer: ENABLED'
Write-Host 'Freqtrade force_entry_enable: TRUE'
Write-Host 'Freqtrade dry_run: TRUE'
Write-Host 'Double dry-run guard: ENABLED'
Write-Host 'Pair duplicate guard: ENABLED'
Write-Host 'Cooldown: 180 sec'
Write-Host 'Max bridge stake: 25 USDT'
Write-Host 'Max bridge leverage: 3x'
Write-Host 'Real-money execution: DISABLED'
Write-Host ('Backup: '+$backup)
