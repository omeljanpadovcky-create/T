$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - DATA ANALYTICS SHADOW ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ''

$base = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/main/astra_analytics_shadow'

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
$backup = Join-Path $app ("backup-before-analytics-shadow-" + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','analytics_shadow.py')) {
    $src = Join-Path $app $f
    if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host "[OK] Backup: $backup"

$tmp = Join-Path $env:TEMP 'myshka_analytics_shadow'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/6] Downloading analytics engine + safe patcher...'
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/analytics_shadow.py') -OutFile (Join-Path $tmp 'analytics_shadow.py')
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/patch_analytics_shadow.py') -OutFile (Join-Path $tmp 'patch_analytics_shadow.py')

Write-Host '[2/6] Installing persistent analytics engine...'
Copy-Item (Join-Path $tmp 'analytics_shadow.py') (Join-Path $app 'analytics_shadow.py') -Force

Write-Host '[3/6] Patching current ASTRA without overwriting existing fixes...'
python (Join-Path $tmp 'patch_analytics_shadow.py') $app
if($LASTEXITCODE -ne 0){ throw "analytics patcher failed: $LASTEXITCODE" }

Write-Host '[4/6] Python syntax check...'
Push-Location $app
try {
    $check = @('api.py','analytics_shadow.py')
    foreach($f in @('market_data.py','context_collector.py','telegram_notify.py')){
        if(Test-Path $f){ $check += $f }
    }
    python -m py_compile @check
    if($LASTEXITCODE -ne 0){ throw "python compile failed: $LASTEXITCODE" }
} catch {
    foreach($f in @('api.py','analytics_shadow.py')) {
        $b = Join-Path $backup $f
        if(Test-Path $b){ Copy-Item $b (Join-Path $app $f) -Force }
        elseif($f -eq 'analytics_shadow.py' -and (Test-Path (Join-Path $app $f))){ Remove-Item (Join-Path $app $f) -Force }
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

Write-Host '[6/6] Health + analytics check...'
$health = $null
for($i=0; $i -lt 40; $i++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
        if($health.status -eq 'ok'){ break }
    } catch {}
}
if(-not $health -or $health.status -ne 'ok') {
    docker logs --tail 150 myshka-astra
    throw 'ASTRA did not become healthy.'
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - DATA ANALYTICS SHADOW ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ("ASTRA health: " + $health.status)
if($health.context_collector){
    Write-Host ("Context collector running: " + $health.context_collector.running)
}
if($health.analytics_shadow){
    Write-Host ("Analytics mode: " + $health.analytics_shadow.mode)
    Write-Host ("Analytics closed: " + $health.analytics_shadow.closed)
    Write-Host ("Analytics DB: " + $health.analytics_shadow.db_path)
}
Write-Host 'Tracks: EDGE / side / pair / RSI / volume / OI / funding / L-S / momentum / BTC / events / time'
Write-Host 'New clean trades only: YES'
Write-Host 'Trading decisions changed: NO (SHADOW only)'
Write-Host 'STRICT +0.05% EDGE: preserved'
Write-Host 'Context 24/7: preserved'
Write-Host 'Rate-limit + stale-settlement guards: preserved'
Write-Host ''
Write-Host 'Telegram command: /analytics'
Write-Host 'Dashboard: Ctrl+F5 after install'
Write-Host "Backup: $backup"
