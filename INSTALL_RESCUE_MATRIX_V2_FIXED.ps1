$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - RESCUE MATRIX V2 FIXED ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$repo='omeljanpadovcky-create/T'
$bundleCommit='51e968b3f09c924bbbc995f4909aa98ceaaa6d39'
$apiRoot='https://api.github.com/repos/'+$repo+'/contents'
$ghHeaders=@{
  'User-Agent'='MYSHKA-ASTRA-Installer'
  'Accept'='application/vnd.github+json'
  'Cache-Control'='no-cache'
}

function Get-GitHubFile {
  param(
    [Parameter(Mandatory=$true)][string]$RepoPath,
    [Parameter(Mandatory=$true)][string]$OutFile
  )
  $encodedPath=($RepoPath -split '/' | ForEach-Object {[uri]::EscapeDataString($_)}) -join '/'
  $uri=$apiRoot+'/'+$encodedPath+'?ref='+$bundleCommit
  $resp=Invoke-RestMethod -UseBasicParsing -Uri $uri -Headers $ghHeaders -TimeoutSec 30
  if(-not $resp.content){throw ('GitHub API returned no content for '+$RepoPath)}
  $b64=([string]$resp.content) -replace '\s',''
  [IO.File]::WriteAllBytes($OutFile,[Convert]::FromBase64String($b64))
}

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

Write-Host '[0/11] Preflight current ASTRA...'
& python -m py_compile (Join-Path $app 'api.py')
if($LASTEXITCODE -ne 0){throw 'Current api.py invalid. Nothing modified.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-rescue-v2-fixed-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('api.py','index.html','rescue_matrix.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_rescue_v2_fixed'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/11] Downloading immutable bundle through GitHub API...'
Get-GitHubFile 'astra_rescue_matrix/rescue_matrix.py' (Join-Path $tmp 'rescue_matrix.py')
Get-GitHubFile 'astra_rescue_matrix/patch_rescue_matrix.py' (Join-Path $tmp 'patch_rescue_matrix.py')
Get-GitHubFile 'astra_rescue_matrix/selftest_rescue_matrix.py' (Join-Path $tmp 'selftest_rescue_matrix.py')
Get-GitHubFile 'index.html' (Join-Path $tmp 'index.html')

Write-Host '[2/11] Verifying exact downloaded Rescue source...'
$rescuePath=Join-Path $tmp 'rescue_matrix.py'
$src=Get-Content $rescuePath -Raw -Encoding UTF8
$initStart=$src.IndexOf('def init() -> dict:')
$nextDef=$src.IndexOf('def _num',$initStart)
if($initStart -lt 0 -or $nextDef -le $initStart){throw 'Cannot locate init() block in downloaded Rescue module.'}
$initBlock=$src.Substring($initStart,$nextDef-$initStart)

if($initBlock -match 'return\s+status\s*\(\s*\)'){
  throw ('STALE/WRONG BUNDLE DETECTED: init() still contains return status(). Commit='+$bundleCommit)
}
if($initBlock -notmatch 'RESCUE_MATRIX_V2_FORWARD_SHADOW_ONLY'){
  throw ('WRONG BUNDLE DETECTED: V2 mode marker absent. Commit='+$bundleCommit)
}
if($src -notmatch 'JEV_APPROVE_x_TECH_3_OF_4'){throw 'Primary anchor marker missing.'}
if($src -notmatch 'movement_cluster_id'){throw 'Movement cluster marker missing.'}
if($src -notmatch 'FORWARD_CONFIRMED'){throw 'Forward confirmation marker missing.'}

$sha=(Get-FileHash $rescuePath -Algorithm SHA256).Hash
Write-Host ('[OK] Bundle commit: '+$bundleCommit) -ForegroundColor Green
Write-Host ('[OK] rescue_matrix.py SHA256: '+$sha) -ForegroundColor Green
Write-Host '[OK] init() recursion check: PASS' -ForegroundColor Green

Write-Host '[3/11] Python compile...'
$py=@(
  (Join-Path $tmp 'rescue_matrix.py'),
  (Join-Path $tmp 'patch_rescue_matrix.py'),
  (Join-Path $tmp 'selftest_rescue_matrix.py')
)
& python -m py_compile @py
if($LASTEXITCODE -ne 0){throw 'Downloaded V2 FIXED Python compile failed. ASTRA unchanged.'}

Write-Host '[4/11] Synthetic self-test...'
$pkg=Join-Path $tmp 'rescuepkg'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $pkg '__init__.py') -Force | Out-Null
Copy-Item (Join-Path $tmp 'rescue_matrix.py') (Join-Path $pkg 'rescue_matrix.py') -Force
Copy-Item (Join-Path $tmp 'selftest_rescue_matrix.py') (Join-Path $pkg 'selftest_rescue_matrix.py') -Force
Push-Location $tmp
try {
  & python -m rescuepkg.selftest_rescue_matrix
  if($LASTEXITCODE -ne 0){throw 'Rescue Matrix V2 FIXED self-test failed. ASTRA unchanged.'}
} finally {Pop-Location}
Write-Host '[OK] Synthetic self-test passed' -ForegroundColor Green

Write-Host '[5/11] Installing SHADOW module + dashboard...'
Copy-Item (Join-Path $tmp 'rescue_matrix.py') (Join-Path $app 'rescue_matrix.py') -Force
Copy-Item (Join-Path $tmp 'index.html') (Join-Path $app 'index.html') -Force

Write-Host '[6/11] Patching API idempotently...'
try {
  & python (Join-Path $tmp 'patch_rescue_matrix.py') $app
  if($LASTEXITCODE -ne 0){throw 'Rescue Matrix API patch failed.'}
  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'rescue_matrix.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  foreach($name in @('api.py','index.html','rescue_matrix.py')){
    $b=Join-Path $backup $name
    $dst=Join-Path $app $name
    if(Test-Path $b){Copy-Item $b $dst -Force}
  }
  throw
}

Write-Host '[7/11] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'docker compose rebuild failed.'}
} finally {Pop-Location}

Write-Host '[8/11] Publishing dashboard...'
docker cp (Join-Path $tmp 'index.html') 'myshka-astra:/data/myshka_dashboard.html'
if($LASTEXITCODE -ne 0){throw 'Dashboard publish failed.'}

Write-Host '[9/11] Health check...'
$health=$null
for($i=0;$i -lt 45;$i++){
  Start-Sleep -Seconds 2
  try{
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed after rebuild.'}

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

Write-Host '[10/11] Rescue endpoint validation...'
$rescue=Invoke-RestMethod 'http://127.0.0.1:8088/rescue-matrix/report' -Headers $headers -TimeoutSec 30
if($rescue.status -ne 'ok'){throw 'Rescue report failed.'}
if($rescue.mode -ne 'RESCUE_MATRIX_V2_FORWARD_SHADOW_ONLY'){throw ('Unexpected Rescue mode: '+$rescue.mode)}
if($rescue.changes_paper_execution -ne $false){throw 'PAPER safety invariant failed.'}
if($rescue.changes_trading_decisions -ne $false){throw 'Trading-decision safety invariant failed.'}
if($rescue.live_execution -ne $false){throw 'LIVE safety invariant failed.'}

Write-Host '[11/11] Opening dashboard...'
$launch='http://127.0.0.1:8088/dashboard#token='+[uri]::EscapeDataString($token)
Start-Process $launch

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - RESCUE MATRIX V2 FIXED INSTALLED ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Bundle commit: '+$bundleCommit)
Write-Host ('Downloaded SHA256: '+$sha)
Write-Host ('ASTRA health: '+$health.status)
Write-Host ('Rescue mode: '+$rescue.mode)
Write-Host 'Primary anchor: JEV APPROVE x TECH 3/4'
Write-Host 'Movement clustering: ENABLED'
Write-Host 'Positive + toxic clusters: ENABLED'
Write-Host 'WATCH + new-forward confirmation: ENABLED'
Write-Host 'Auto gate: OFF'
Write-Host 'PAPER execution changed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: '+$backup)
