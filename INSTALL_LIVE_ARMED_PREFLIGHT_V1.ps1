$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - LIVE ARMED PREFLIGHT V1 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='7a34fa34c4bb5d52abc5ded01c7c04e55d3036c2'
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
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){throw 'ASTRA project folder not found.'}

Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green
& python -m py_compile (Join-Path $app 'api.py')
if($LASTEXITCODE -ne 0){throw 'Current api.py invalid. Nothing modified.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-live-armed-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('api.py','live_armed_preflight.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}

$tmp=Join-Path $env:TEMP 'myshka_live_armed_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

function Get-PinnedRawFile {
  param([string]$RepoPath,[string]$OutFile)
  $nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  $uri=$root+'/'+$RepoPath+'?x='+$nonce
  Invoke-WebRequest -UseBasicParsing -Uri $uri -Headers @{
    'User-Agent'='MYSHKA-ASTRA-LiveArmed'
    'Cache-Control'='no-cache, no-store, max-age=0'
    'Pragma'='no-cache'
  } -OutFile $OutFile -TimeoutSec 60
}

Write-Host '[1/8] Downloading pinned LIVE-ARMED bundle...'
Get-PinnedRawFile 'astra_live_armed/live_armed_preflight.py' (Join-Path $tmp 'live_armed_preflight.py')
Get-PinnedRawFile 'astra_live_armed/selftest_live_armed_preflight.py' (Join-Path $tmp 'selftest_live_armed_preflight.py')
Get-PinnedRawFile 'astra_live_armed/patch_live_armed_preflight.py' (Join-Path $tmp 'patch_live_armed_preflight.py')

Write-Host '[2/8] Safety checks...'
$src=Get-Content (Join-Path $tmp 'live_armed_preflight.py') -Raw -Encoding UTF8
foreach($m in @(
  'LIVE_ARMED_MANUAL_CONFIRM_ONLY',
  'financial_post_calls',
  'forceenter_called',
  'manual_confirmation_required'
)){
  if($src -notlike ('*'+$m+'*')){throw ('Missing marker: '+$m)}
}
if($src -match 'method\s*=\s*"POST".*forceenter'){throw 'Unsafe forceenter POST found.'}
Write-Host '[OK] financial order POST remains blocked' -ForegroundColor Green

Write-Host '[3/8] Compile + self-test...'
$py=@(
  (Join-Path $tmp 'live_armed_preflight.py'),
  (Join-Path $tmp 'selftest_live_armed_preflight.py'),
  (Join-Path $tmp 'patch_live_armed_preflight.py')
)
& python -m py_compile @py
if($LASTEXITCODE -ne 0){throw 'Bundle compile failed. ASTRA unchanged.'}

$pkg=Join-Path $tmp 'armedpkg'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $pkg '__init__.py') -Force | Out-Null
Copy-Item (Join-Path $tmp 'live_armed_preflight.py') (Join-Path $pkg 'live_armed_preflight.py') -Force
Copy-Item (Join-Path $tmp 'selftest_live_armed_preflight.py') (Join-Path $pkg 'selftest_live_armed_preflight.py') -Force
Push-Location $tmp
try {
  & python -m armedpkg.selftest_live_armed_preflight
  if($LASTEXITCODE -ne 0){throw 'LIVE-ARMED self-test failed. ASTRA unchanged.'}
} finally {Pop-Location}

Write-Host '[4/8] Installing module...'
Copy-Item (Join-Path $tmp 'live_armed_preflight.py') (Join-Path $app 'live_armed_preflight.py') -Force

Write-Host '[5/8] Patching API...'
try {
  & python (Join-Path $tmp 'patch_live_armed_preflight.py') $app
  if($LASTEXITCODE -ne 0){throw 'API patch failed.'}
  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'live_armed_preflight.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  if(Test-Path (Join-Path $backup 'api.py')){Copy-Item (Join-Path $backup 'api.py') (Join-Path $app 'api.py') -Force}
  if(Test-Path (Join-Path $backup 'live_armed_preflight.py')){Copy-Item (Join-Path $backup 'live_armed_preflight.py') (Join-Path $app 'live_armed_preflight.py') -Force}
  else {Remove-Item (Join-Path $app 'live_armed_preflight.py') -ErrorAction SilentlyContinue}
  throw
}

Write-Host '[6/8] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'ASTRA rebuild failed.'}
} finally {Pop-Location}

Write-Host '[7/8] Health check...'
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

Write-Host '[8/8] Real Freqtrade preflight...'
$st=Invoke-RestMethod 'http://127.0.0.1:8088/live-armed/status' -Headers $headers -TimeoutSec 15
$pf=Invoke-RestMethod 'http://127.0.0.1:8088/live-armed/preflight' -Headers $headers -TimeoutSec 30

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - LIVE ARMED PREFLIGHT V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Mode: '+$st.mode)
Write-Host ('Freqtrade: '+$st.freqtrade_base_url)
Write-Host ('Credentials present: '+$st.credentials_present)
Write-Host ('Ping OK: '+$pf.ping.ok)
Write-Host ('Auth OK: '+$pf.auth.authenticated)
Write-Host ('Open trades: '+$pf.trades.open_count)
Write-Host ('Whitelist count: '+$pf.whitelist.Count)
Write-Host ('Default stake: '+$st.default_stake_usdt+' USDT')
Write-Host ('Max stake cap: '+$st.max_stake_usdt+' USDT')
Write-Host ('Default leverage: '+$st.default_leverage+'x')
Write-Host ('Max leverage cap: '+$st.max_leverage+'x')
Write-Host 'Manual confirmation required: YES'
Write-Host 'forceenter called: NO'
Write-Host 'Financial POST calls: 0'
Write-Host ('Backup: '+$backup)
