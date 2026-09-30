$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - LOCAL BRIDGE CORS/PNA HOTFIX ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = 'ac7e8b352a5b8dae8d272b31b1949da041e05098'
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
$backup = Join-Path $app ('backup-before-local-bridge-cors-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item (Join-Path $app 'api.py') (Join-Path $backup 'api.py') -Force
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_local_bridge_cors_hotfix'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/6] Downloading patcher...'
Invoke-WebRequest -UseBasicParsing -Uri ($root + '/astra_bridge_hotfix/patch_local_bridge_cors_pna.py') -OutFile (Join-Path $tmp 'patch_local_bridge_cors_pna.py')
& python -m py_compile (Join-Path $tmp 'patch_local_bridge_cors_pna.py')
if($LASTEXITCODE -ne 0){ throw 'Patcher syntax invalid. Local ASTRA not modified.' }

Write-Host '[2/6] Dry-run patch on a TEMP copy...'
$dry = Join-Path $tmp 'dry'
New-Item -ItemType Directory -Path $dry -Force | Out-Null
Copy-Item (Join-Path $app 'api.py') (Join-Path $dry 'api.py') -Force
& python (Join-Path $tmp 'patch_local_bridge_cors_pna.py') $dry
if($LASTEXITCODE -ne 0){ throw 'Dry-run patch failed. Local ASTRA not modified.' }
& python -m py_compile (Join-Path $dry 'api.py')
if($LASTEXITCODE -ne 0){ throw 'Dry-run api.py compile failed. Local ASTRA not modified.' }
Write-Host '[OK] Dry-run compile passed.' -ForegroundColor Green

Write-Host '[3/6] Patching local api.py...'
try {
  & python (Join-Path $tmp 'patch_local_bridge_cors_pna.py') $app
  if($LASTEXITCODE -ne 0){ throw 'Local API patch failed.' }
  & python -m py_compile (Join-Path $app 'api.py')
  if($LASTEXITCODE -ne 0){ throw 'Patched api.py compile failed.' }
} catch {
  Copy-Item (Join-Path $backup 'api.py') (Join-Path $app 'api.py') -Force
  Write-Host '[ROLLBACK] Previous api.py restored.' -ForegroundColor Yellow
  throw
}

Write-Host '[4/6] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[5/6] Checking GET /health...'
$health = $null
for($i=0; $i -lt 40; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA GET /health failed after hotfix.' }

Write-Host '[6/6] Browser-style CORS / Private Network preflight...'
$origin = 'https://omeljanpadovcky-create.github.io'
$preHeaders = @{
  'Origin' = $origin
  'Access-Control-Request-Method' = 'GET'
  'Access-Control-Request-Headers' = 'x-myshka-token'
  'Access-Control-Request-Private-Network' = 'true'
}
$pre = Invoke-WebRequest -UseBasicParsing -Method Options -Uri 'http://127.0.0.1:8088/health' -Headers $preHeaders -TimeoutSec 8

$allowOrigin = [string]$pre.Headers['Access-Control-Allow-Origin']
$allowPrivate = [string]$pre.Headers['Access-Control-Allow-Private-Network']
$allowHeaders = [string]$pre.Headers['Access-Control-Allow-Headers']

if($allowOrigin -ne $origin){ throw ('CORS origin check failed: ' + $allowOrigin) }
if($allowPrivate.ToLower() -ne 'true'){ throw ('Private Network check failed: ' + $allowPrivate) }
if($allowHeaders.ToLower() -notmatch 'x-myshka-token'){ throw ('CORS token header check failed: ' + $allowHeaders) }

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - LOCAL BRIDGE CORS/PNA HOTFIX ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Allow-Origin: ' + $allowOrigin)
Write-Host ('Allow-Private-Network: ' + $allowPrivate)
Write-Host ('Allow-Headers: ' + $allowHeaders)
Write-Host ''
Write-Host 'Trading decisions changed: NO'
Write-Host 'PAPER databases changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: ' + $backup)
