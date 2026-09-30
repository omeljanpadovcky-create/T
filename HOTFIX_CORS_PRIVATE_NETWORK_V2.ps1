$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - CORS PRIVATE NETWORK V2 HOTFIX ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '081ffef588e1a3fe8094be1bdefdb827a6395a3e'
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
$backup = Join-Path $app ('backup-before-cors-private-network-v2-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item (Join-Path $app 'api.py') (Join-Path $backup 'api.py') -Force
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_cors_private_network_v2'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/6] Downloading exact CORS patcher...'
Invoke-WebRequest -UseBasicParsing -Uri ($root + '/astra_bridge_hotfix/patch_enable_cors_private_network.py') -OutFile (Join-Path $tmp 'patch_enable_cors_private_network.py')
& python -m py_compile (Join-Path $tmp 'patch_enable_cors_private_network.py')
if($LASTEXITCODE -ne 0){ throw 'Patcher syntax invalid. Local ASTRA not modified.' }

Write-Host '[2/6] Dry-run against TEMP api.py...'
$dry = Join-Path $tmp 'dry'
New-Item -ItemType Directory -Path $dry -Force | Out-Null
Copy-Item (Join-Path $app 'api.py') (Join-Path $dry 'api.py') -Force
& python (Join-Path $tmp 'patch_enable_cors_private_network.py') $dry
if($LASTEXITCODE -ne 0){ throw 'Dry-run patch failed. Local ASTRA not modified.' }
& python -m py_compile (Join-Path $dry 'api.py')
if($LASTEXITCODE -ne 0){ throw 'Dry-run api.py compile failed. Local ASTRA not modified.' }
Write-Host '[OK] Dry-run passed.' -ForegroundColor Green

Write-Host '[3/6] Patching actual api.py...'
try {
  & python (Join-Path $tmp 'patch_enable_cors_private_network.py') $app
  if($LASTEXITCODE -ne 0){ throw 'api.py patch failed.' }
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

Write-Host '[5/6] Waiting for GET /health...'
$health = $null
for($i=0; $i -lt 40; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA GET /health failed.' }

Write-Host '[6/6] Testing the exact browser PNA preflight...'
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

if($pre.StatusCode -ne 200 -and $pre.StatusCode -ne 204){ throw ('Preflight HTTP ' + $pre.StatusCode) }
if($allowOrigin -ne $origin){ throw ('CORS origin failed: ' + $allowOrigin) }
if($allowPrivate.ToLower() -ne 'true'){ throw ('Private Network failed: ' + $allowPrivate) }
if($allowHeaders.ToLower() -notmatch 'x-myshka-token'){ throw ('Token header failed: ' + $allowHeaders) }

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - CORS PRIVATE NETWORK V2 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Preflight HTTP: ' + $pre.StatusCode)
Write-Host ('Allow-Origin: ' + $allowOrigin)
Write-Host ('Allow-Private-Network: ' + $allowPrivate)
Write-Host ('Allow-Headers: ' + $allowHeaders)
Write-Host ''
Write-Host 'Trading decisions changed: NO'
Write-Host 'PAPER databases changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: ' + $backup)
