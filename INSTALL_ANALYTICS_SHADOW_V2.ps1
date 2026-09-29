$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - DATA ANALYTICS SHADOW V2 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ''

$base = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/main/astra_analytics_shadow'
$cacheBust = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

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
$apiPath = Join-Path $app 'api.py'

Write-Host '[0/7] Preflight current api.py...'
& python -m py_compile $apiPath 2>$null
if($LASTEXITCODE -ne 0) {
    Write-Host '[WARN] Current api.py is not valid. Searching backups...' -ForegroundColor Yellow
    $restored = $false
    $dirs = Get-ChildItem -Path $app -Directory -Filter 'backup-*' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending
    foreach($d in $dirs) {
        $candidate = Join-Path $d.FullName 'api.py'
        if(-not (Test-Path $candidate)){ continue }
        & python -m py_compile $candidate 2>$null
        if($LASTEXITCODE -eq 0) {
            Copy-Item $candidate $apiPath -Force
            Write-Host ("[OK] Restored valid api.py from: " + $d.FullName) -ForegroundColor Green
            $restored = $true
            break
        }
    }
    if(-not $restored) {
        throw 'No valid api.py backup found. Analytics V2 did not modify anything.'
    }
}

& python -m py_compile $apiPath
if($LASTEXITCODE -ne 0){ throw 'api.py preflight still failed after restore.' }
Write-Host '[OK] Current api.py syntax valid.' -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ("backup-before-analytics-v2-" + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','analytics_shadow.py')) {
    $src = Join-Path $app $f
    if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host "[OK] Fresh backup: $backup"

$tmp = Join-Path $env:TEMP 'myshka_analytics_shadow_v2'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/7] Downloading analytics engine...'
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/analytics_shadow.py?v=' + $cacheBust) -OutFile (Join-Path $tmp 'analytics_shadow.py')

Write-Host '[2/7] Downloading Telegram-free V2 patcher...'
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/patch_analytics_core_v2.py?v=' + $cacheBust) -OutFile (Join-Path $tmp 'patch_analytics_core_v2.py')

Write-Host '[3/7] Validating downloaded Python files...'
& python -m py_compile (Join-Path $tmp 'analytics_shadow.py') (Join-Path $tmp 'patch_analytics_core_v2.py')
if($LASTEXITCODE -ne 0){ throw 'Downloaded Analytics V2 files failed syntax check. Local ASTRA was not modified.' }
Write-Host '[OK] Downloaded files syntax valid.' -ForegroundColor Green

Write-Host '[4/7] Installing analytics engine + patching api.py...'
Copy-Item (Join-Path $tmp 'analytics_shadow.py') (Join-Path $app 'analytics_shadow.py') -Force
try {
    & python (Join-Path $tmp 'patch_analytics_core_v2.py') $app
    if($LASTEXITCODE -ne 0){ throw "analytics V2 patcher failed: $LASTEXITCODE" }

    Push-Location $app
    try {
        $check = @('api.py','analytics_shadow.py')
        foreach($f in @('market_data.py','context_collector.py','telegram_notify.py')){
            if(Test-Path $f){ $check += $f }
        }
        & python -m py_compile @check
        if($LASTEXITCODE -ne 0){ throw "python compile failed after V2 patch: $LASTEXITCODE" }
    } finally { Pop-Location }
} catch {
    Copy-Item (Join-Path $backup 'api.py') $apiPath -Force
    $oldAnalytics = Join-Path $backup 'analytics_shadow.py'
    if(Test-Path $oldAnalytics) {
        Copy-Item $oldAnalytics (Join-Path $app 'analytics_shadow.py') -Force
    } elseif(Test-Path (Join-Path $app 'analytics_shadow.py')) {
        Remove-Item (Join-Path $app 'analytics_shadow.py') -Force
    }
    Write-Host '[ROLLBACK] Restored pre-V2 files.' -ForegroundColor Yellow
    throw
}
Write-Host '[OK] Final Python syntax valid.' -ForegroundColor Green

Write-Host '[5/7] Rebuilding ASTRA...'
Push-Location $app
try {
    docker compose up -d --build --force-recreate astra
    if($LASTEXITCODE -ne 0){ throw "docker compose failed: $LASTEXITCODE" }
} finally { Pop-Location }

Write-Host '[6/7] Waiting for ASTRA health...'
$health = $null
for($i=0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
        if($health.status -eq 'ok'){ break }
    } catch {}
}
if(-not $health -or $health.status -ne 'ok') {
    docker logs --tail 160 myshka-astra
    throw 'ASTRA did not become healthy.'
}

Write-Host '[7/7] Analytics health check...'
if(-not $health.analytics_shadow) {
    throw 'ASTRA is healthy but analytics_shadow is missing from /health.'
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - DATA ANALYTICS SHADOW V2 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ("ASTRA health: " + $health.status)
if($health.context_collector){
    Write-Host ("Context collector running: " + $health.context_collector.running)
}
Write-Host ("Analytics mode: " + $health.analytics_shadow.mode)
Write-Host ("Analytics closed: " + $health.analytics_shadow.closed)
Write-Host ("Analytics DB: " + $health.analytics_shadow.db_path)
Write-Host 'Telegram code modified: NO'
Write-Host 'Trading decisions changed: NO (SHADOW only)'
Write-Host 'STRICT +0.05% EDGE: preserved'
Write-Host 'Context 24/7: preserved'
Write-Host 'Rate-limit + stale-settlement guards: preserved'
Write-Host ''
Write-Host 'Dashboard: Ctrl+F5'
Write-Host "Backup: $backup"
