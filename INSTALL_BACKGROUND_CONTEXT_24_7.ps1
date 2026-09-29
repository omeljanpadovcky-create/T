$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '====================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - BACKGROUND CONTEXT 24/7 (SHADOW) ' -ForegroundColor Yellow
Write-Host '====================================================' -ForegroundColor Cyan
Write-Host ''

$repoRaw = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/main/astra_context_24_7'

$app = $null
try {
    $raw = docker inspect myshka-astra 2>$null | ConvertFrom-Json
    if ($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir') {
        $app = $raw[0].Config.Labels.'com.docker.compose.project.working_dir'
    }
} catch {}

if (-not $app) {
    $fallback = Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
    if (Test-Path (Join-Path $fallback 'Dockerfile')) { $app = $fallback }
}
if (-not $app -or -not (Test-Path (Join-Path $app 'Dockerfile'))) {
    throw 'ASTRA project folder not found. Start Docker + MYSHKA/ASTRA first.'
}

Write-Host "[OK] ASTRA project: $app" -ForegroundColor Green
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ("backup-before-context-24x7-" + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','telegram_notify.py','context_collector.py')) {
    $src = Join-Path $app $f
    if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host "[OK] Backup: $backup"

$tmp = Join-Path $env:TEMP 'myshka_context_24_7'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/6] Downloading collector + safe patcher...'
Invoke-WebRequest -UseBasicParsing -Uri ($repoRaw + '/context_collector.py') -OutFile (Join-Path $tmp 'context_collector.py')
Invoke-WebRequest -UseBasicParsing -Uri ($repoRaw + '/patch_context_24_7.py') -OutFile (Join-Path $tmp 'patch_context_24_7.py')

Write-Host '[2/6] Installing context collector...'
Copy-Item (Join-Path $tmp 'context_collector.py') (Join-Path $app 'context_collector.py') -Force

Write-Host '[3/6] Patching current v9.7 without overwriting other fixes...'
python (Join-Path $tmp 'patch_context_24_7.py') $app
if($LASTEXITCODE -ne 0){ throw "context patcher failed: $LASTEXITCODE" }

Write-Host '[4/6] Python syntax check...'
Push-Location $app
try {
    python -m py_compile api.py telegram_notify.py context_collector.py
    if($LASTEXITCODE -ne 0){ throw "python compile failed: $LASTEXITCODE" }
} catch {
    foreach($f in @('api.py','telegram_notify.py','context_collector.py')) {
        $b = Join-Path $backup $f
        if(Test-Path $b){ Copy-Item $b (Join-Path $app $f) -Force }
    }
    throw
} finally { Pop-Location }
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[5/6] Rebuilding ASTRA...'
Push-Location $app
try {
    docker compose up -d --build --force-recreate astra
    if($LASTEXITCODE -ne 0){ throw "docker compose failed: $LASTEXITCODE" }
} finally { Pop-Location }

Write-Host '[6/6] Health + collector check...'
$health = $null
for($i=0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
        if($health.status -eq 'ok'){ break }
    } catch {}
}
if(-not $health -or $health.status -ne 'ok') {
    docker logs --tail 120 myshka-astra
    throw 'ASTRA did not become healthy.'
}

$ctx = $null
for($i=0; $i -lt 30; $i++) {
    try {
        $ctx = Invoke-RestMethod 'http://127.0.0.1:8088/context/status' -TimeoutSec 4
        if($ctx.running){ break }
    } catch {}
    Start-Sleep -Seconds 1
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - BACKGROUND CONTEXT 24/7 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ("ASTRA health: " + $health.status)
if($ctx){
    Write-Host ("Context running: " + $ctx.running)
    Write-Host ("Collect interval: " + $ctx.interval_sec + " sec")
    Write-Host ("History window: " + $ctx.history_minutes + " min")
    Write-Host ("Context DB: " + $ctx.db_path)
}
Write-Host 'Mode: SHADOW - context is recorded, but cannot create/veto a trade yet.'
Write-Host 'Your existing STRICT +0.05% EDGE patch is preserved.'
Write-Host ''
Write-Host 'Telegram scan messages will show CTX SHADOW lines.'
Write-Host 'Status: http://127.0.0.1:8088/context/status'
Write-Host "Backup: $backup"
