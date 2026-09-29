$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - BYBIT RATE LIMIT + SETTLE GUARD ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ''

$rawUrl = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/main/astra_rate_guard/patch_rate_limit_guard.py'

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
$backup = Join-Path $app ("backup-before-rate-guard-" + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','market_data.py')) {
    $src = Join-Path $app $f
    if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host "[OK] Backup: $backup"

$tmp = Join-Path $env:TEMP 'myshka_rate_guard'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/5] Downloading safe patcher...'
Invoke-WebRequest -UseBasicParsing -Uri $rawUrl -OutFile (Join-Path $tmp 'patch_rate_limit_guard.py')

Write-Host '[2/5] Applying cache / backoff / stale-settlement guards...'
python (Join-Path $tmp 'patch_rate_limit_guard.py') $app
if($LASTEXITCODE -ne 0){ throw "rate guard patcher failed: $LASTEXITCODE" }

Write-Host '[3/5] Python syntax check...'
Push-Location $app
try {
    $check = @('api.py','market_data.py')
    if(Test-Path 'context_collector.py'){ $check += 'context_collector.py' }
    python -m py_compile @check
    if($LASTEXITCODE -ne 0){ throw "python compile failed: $LASTEXITCODE" }
} catch {
    foreach($f in @('api.py','market_data.py')) {
        $b = Join-Path $backup $f
        if(Test-Path $b){ Copy-Item $b (Join-Path $app $f) -Force }
    }
    throw
} finally { Pop-Location }
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[4/5] Rebuilding ASTRA...'
Push-Location $app
try {
    docker compose up -d --build --force-recreate astra
    if($LASTEXITCODE -ne 0){ throw "docker compose failed: $LASTEXITCODE" }
} finally { Pop-Location }

Write-Host '[5/5] Health check...'
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

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - RATE LIMIT GUARD ACTIVE ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ("ASTRA health: " + $health.status)
if($health.context_collector){
    Write-Host ("Context collector running: " + $health.context_collector.running)
}
Write-Host '1m kline cache: ON'
Write-Host 'Bybit request pacing/backoff: ON'
Write-Host 'Concurrent ASTRA scans: BLOCKED'
Write-Host 'Stale 5m settlement >90s: SKIP (not learner/P&L)'
Write-Host 'STRICT +0.05% EDGE: preserved'
Write-Host ''
Write-Host "Backup: $backup"
Write-Host 'Now open the dashboard and press Ctrl+F5.'
