$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - LIVE DRY RUN V1 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='7bc44a67b092262634cd40bf23ebe062c2cf0b56'
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
Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

Write-Host '[0/9] Preflight current api.py...'
& python -m py_compile (Join-Path $app 'api.py')
if($LASTEXITCODE -ne 0){throw 'Current api.py invalid. Nothing modified.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-live-dry-run-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('api.py','live_dry_run.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_live_dry_run_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

function Get-PinnedRawFile {
  param([string]$RepoPath,[string]$OutFile)
  $nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  $uri=$root+'/'+$RepoPath+'?x='+$nonce
  Invoke-WebRequest -UseBasicParsing -Uri $uri -Headers @{
    'User-Agent'='MYSHKA-ASTRA-LiveDryRun'
    'Cache-Control'='no-cache, no-store, max-age=0'
    'Pragma'='no-cache'
  } -OutFile $OutFile -TimeoutSec 60
}

Write-Host '[1/9] Downloading pinned dry-run bundle...'
Get-PinnedRawFile 'astra_live_dry_run/live_dry_run.py' (Join-Path $tmp 'live_dry_run.py')
Get-PinnedRawFile 'astra_live_dry_run/selftest_live_dry_run.py' (Join-Path $tmp 'selftest_live_dry_run.py')
Get-PinnedRawFile 'astra_live_dry_run/patch_live_dry_run.py' (Join-Path $tmp 'patch_live_dry_run.py')

Write-Host '[2/9] Safety marker checks...'
$src=Get-Content (Join-Path $tmp 'live_dry_run.py') -Raw -Encoding UTF8
foreach($m in @(
  'LIVE_DRY_RUN_ONLY',
  'DRY_RUN_HARD_BLOCK',
  '"create_order_called": False',
  '"live_execution": False',
  '"execution_blocked": True'
)){
  if($src -notlike ('*'+$m+'*')){throw ('Missing hard-block marker: '+$m)}
}
if($src -match '\.create_order\s*\('){throw 'Unsafe create_order() call found in dry-run module.'}
if($src -match 'requests\.(post|put|patch|delete)\s*\('){throw 'Unsafe external write HTTP call found in dry-run module.'}
Write-Host '[OK] No exchange/order write call present' -ForegroundColor Green

Write-Host '[3/9] Compile + synthetic self-test...'
$py=@(
  (Join-Path $tmp 'live_dry_run.py'),
  (Join-Path $tmp 'selftest_live_dry_run.py'),
  (Join-Path $tmp 'patch_live_dry_run.py')
)
& python -m py_compile @py
if($LASTEXITCODE -ne 0){throw 'Dry-run bundle compile failed. ASTRA unchanged.'}

$pkg=Join-Path $tmp 'drypkg'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $pkg '__init__.py') -Force | Out-Null
Copy-Item (Join-Path $tmp 'live_dry_run.py') (Join-Path $pkg 'live_dry_run.py') -Force
Copy-Item (Join-Path $tmp 'selftest_live_dry_run.py') (Join-Path $pkg 'selftest_live_dry_run.py') -Force
Push-Location $tmp
try {
  & python -m drypkg.selftest_live_dry_run
  if($LASTEXITCODE -ne 0){throw 'LIVE DRY RUN self-test failed. ASTRA unchanged.'}
} finally {Pop-Location}

Write-Host '[4/9] Installing module only...'
Copy-Item (Join-Path $tmp 'live_dry_run.py') (Join-Path $app 'live_dry_run.py') -Force

Write-Host '[5/9] Patching API observer/endpoints...'
try {
  & python (Join-Path $tmp 'patch_live_dry_run.py') $app
  if($LASTEXITCODE -ne 0){throw 'LIVE DRY RUN API patch failed.'}

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'live_dry_run.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  $apiBackup=Join-Path $backup 'api.py'
  if(Test-Path $apiBackup){Copy-Item $apiBackup (Join-Path $app 'api.py') -Force}
  $modBackup=Join-Path $backup 'live_dry_run.py'
  if(Test-Path $modBackup){Copy-Item $modBackup (Join-Path $app 'live_dry_run.py') -Force}
  else {Remove-Item (Join-Path $app 'live_dry_run.py') -ErrorAction SilentlyContinue}
  throw
}

Write-Host '[6/9] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'ASTRA rebuild failed.'}
} finally {Pop-Location}

Write-Host '[7/9] Health check...'
$health=$null
for($i=0;$i -lt 45;$i++){
  Start-Sleep -Seconds 2
  try{
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed.'}

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

Write-Host '[8/9] Validating hard-blocked endpoint...'
$st=Invoke-RestMethod 'http://127.0.0.1:8088/live-dry-run/status' -Headers $headers -TimeoutSec 15
if($st.mode -ne 'LIVE_DRY_RUN_ONLY'){throw ('Unexpected mode: '+$st.mode)}
if($st.execution_blocked -ne $true){throw 'Execution hard block is not active.'}
if([int]$st.create_order_calls -ne 0){throw 'Unsafe: create_order_calls is not zero.'}
if($st.live_execution -ne $false){throw 'Unsafe: live_execution is not false.'}
if($st.paper_execution_changed -ne $false){throw 'PAPER changed unexpectedly.'}
if($st.trading_decision_changed -ne $false){throw 'Trading decision changed unexpectedly.'}

Write-Host '[9/9] Reading latest would-send previews...'
$recent=Invoke-RestMethod 'http://127.0.0.1:8088/live-dry-run/recent?limit=5' -Headers $headers -TimeoutSec 15

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - LIVE DRY RUN V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Mode: '+$st.mode)
Write-Host ('Notional preview: '+$st.notional_usdt+' USDT')
Write-Host ('Leverage preview: '+$st.leverage+'x')
Write-Host ('SL preview: '+$st.sl_pct+'%')
Write-Host ('TP preview: '+$st.tp_pct+'%')
Write-Host ('Recent previews: '+$recent.items.Count)
Write-Host 'Execution blocked: YES'
Write-Host 'create_order calls: 0'
Write-Host 'PAPER execution changed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'LIVE execution: NO'
Write-Host ('Backup: '+$backup)
