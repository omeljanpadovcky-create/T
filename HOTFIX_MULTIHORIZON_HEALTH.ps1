$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - MULTIHORIZON HEALTH HOTFIX ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '83f4310e269e9bc97caaf2fa2f634d40bee94f44'
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
if (-not $app -or -not (Test-Path (Join-Path $app 'api.py'))) { throw 'ASTRA project folder not found.' }
Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-multihorizon-health-hotfix-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$old = Join-Path $app 'multihorizon_shadow.py'
if(Test-Path $old){ Copy-Item $old (Join-Path $backup 'multihorizon_shadow.py') -Force }

$tmp = Join-Path $env:TEMP 'myshka_multihorizon_health_hotfix'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/5] Downloading fixed Multi-Horizon module...'
Invoke-WebRequest -UseBasicParsing -Uri ($root + '/astra_multihorizon_shadow/multihorizon_shadow.py') -OutFile (Join-Path $tmp 'multihorizon_shadow.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root + '/astra_multihorizon_shadow/selftest_multihorizon_shadow.py') -OutFile (Join-Path $tmp 'selftest_multihorizon_shadow.py')

Write-Host '[2/5] Syntax + isolated self-test...'
& python -m py_compile (Join-Path $tmp 'multihorizon_shadow.py') (Join-Path $tmp 'selftest_multihorizon_shadow.py')
if($LASTEXITCODE -ne 0){ throw 'HOTFIX syntax failed. Local ASTRA not modified.' }
Push-Location $tmp
try {
  & python '.\selftest_multihorizon_shadow.py'
  if($LASTEXITCODE -ne 0){ throw 'HOTFIX self-test failed. Local ASTRA not modified.' }
} finally { Pop-Location }

Write-Host '[3/5] Installing fixed SHADOW module...'
Copy-Item (Join-Path $tmp 'multihorizon_shadow.py') (Join-Path $app 'multihorizon_shadow.py') -Force
Push-Location $app
try {
  & python -m py_compile 'api.py' 'multihorizon_shadow.py'
  if($LASTEXITCODE -ne 0){
    if(Test-Path (Join-Path $backup 'multihorizon_shadow.py')){ Copy-Item (Join-Path $backup 'multihorizon_shadow.py') (Join-Path $app 'multihorizon_shadow.py') -Force }
    throw 'Final compile failed; previous module restored.'
  }
} finally { Pop-Location }

Write-Host '[4/5] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[5/5] Checking real GET /health...'
$health = $null
for($i=0; $i -lt 30; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'GET /health still not responding.' }

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - MULTIHORIZON HEALTH HOTFIX ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Multi-Horizon mode: ' + $health.multihorizon_shadow.mode)
Write-Host 'Trading decisions changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host 'Extra market API calls: NO'
Write-Host ('Backup: ' + $backup)
