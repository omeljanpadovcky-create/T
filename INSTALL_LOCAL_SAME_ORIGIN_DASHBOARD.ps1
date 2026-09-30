$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - LOCAL SAME-ORIGIN DASHBOARD FIX ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '21c01bc9be0669d2eea6beefba3a5395b44dcc96'
$root = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/' + $bundleCommit

$app = $null
try {
  $raw = docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if ($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir') {
    $app = $raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
} catch {}

if (-not $app) {
  $fallback = Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if (Test-Path (Join-Path $fallback 'api.py')) { $app = $fallback }
}
if (-not $app -or -not (Test-Path (Join-Path $app 'api.py'))) {
  throw 'ASTRA project folder not found.'
}

Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-local-dashboard-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('api.py','index.html')){
  $src = Join-Path $app $name
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $name) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_local_dashboard_fix'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/7] Downloading current dashboard + patcher...'
Invoke-WebRequest -UseBasicParsing -Uri ($root + '/index.html') -OutFile (Join-Path $tmp 'index.html')
Invoke-WebRequest -UseBasicParsing -Uri ($root + '/astra_local_dashboard/patch_local_dashboard.py') -OutFile (Join-Path $tmp 'patch_local_dashboard.py')

Write-Host '[2/7] Validating downloaded files...'
& python -m py_compile (Join-Path $tmp 'patch_local_dashboard.py')
if($LASTEXITCODE -ne 0){ throw 'Dashboard patcher syntax invalid. Local ASTRA not modified.' }

$html = Get-Content (Join-Path $tmp 'index.html') -Raw
if($html -notmatch 'localAstraOrigin' -or $html -notmatch 'POSTV2_300'){
  throw 'Downloaded dashboard is not the expected same-origin/Post-V2 build.'
}
Write-Host '[OK] Downloaded dashboard validated.' -ForegroundColor Green

Write-Host '[3/7] Installing current index.html...'
Copy-Item (Join-Path $tmp 'index.html') (Join-Path $app 'index.html') -Force

Write-Host '[4/7] Patching api.py with /dashboard route...'
try {
  & python (Join-Path $tmp 'patch_local_dashboard.py') $app
  if($LASTEXITCODE -ne 0){ throw 'Local dashboard API patch failed.' }

  Push-Location $app
  try {
    & python -m py_compile 'api.py'
    if($LASTEXITCODE -ne 0){ throw 'api.py compile failed.' }
  } finally { Pop-Location }
} catch {
  if(Test-Path (Join-Path $backup 'api.py')){
    Copy-Item (Join-Path $backup 'api.py') (Join-Path $app 'api.py') -Force
  }
  if(Test-Path (Join-Path $backup 'index.html')){
    Copy-Item (Join-Path $backup 'index.html') (Join-Path $app 'index.html') -Force
  }
  throw
}

Write-Host '[5/7] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[6/7] Publishing dashboard into persistent /data volume...'
docker cp (Join-Path $tmp 'index.html') 'myshka-astra:/data/myshka_dashboard.html'
if($LASTEXITCODE -ne 0){ throw 'docker cp dashboard -> /data failed.' }
Write-Host '[OK] Dashboard copied to /data/myshka_dashboard.html' -ForegroundColor Green

Write-Host '[6.5/7] Checking /health and local dashboard...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health failed after rebuild.' }

$page = Invoke-WebRequest -UseBasicParsing 'http://127.0.0.1:8088/dashboard' -TimeoutSec 10
if($page.StatusCode -ne 200){ throw 'Local dashboard HTTP check failed.' }
if($page.Content -notmatch 'MYSHKA / ASTRA Trading Lab' -or $page.Content -notmatch 'localAstraOrigin'){
  throw 'Local dashboard content check failed.'
}

Write-Host '[7/7] Opening same-origin dashboard...'
Start-Process 'http://127.0.0.1:8088/dashboard'

Write-Host ''
Write-Host '======================================================' -ForegroundColor Green
Write-Host ' READY - LOCAL SAME-ORIGIN DASHBOARD ' -ForegroundColor Green
Write-Host '======================================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host 'Dashboard: http://127.0.0.1:8088/dashboard'
Write-Host 'Bridge path: SAME-ORIGIN'
Write-Host 'CORS/PNA dependency on desktop: NO'
Write-Host 'GitHub Pages -> localhost dependency on desktop: NO'
Write-Host 'Trading logic changed: NO'
Write-Host 'Binance/Post-V2 changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: ' + $backup)
