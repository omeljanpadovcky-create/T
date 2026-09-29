$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - COUNTERFACTUAL ANALYTICS SHADOW ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ''

$base = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/main/astra_counterfactual_shadow'
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
& python -m py_compile $apiPath
if($LASTEXITCODE -ne 0) {
    throw 'Current api.py is not valid. Counterfactual installer did not modify anything.'
}
Write-Host '[OK] Current api.py syntax valid.' -ForegroundColor Green

if(-not (Test-Path (Join-Path $app 'analytics_shadow.py'))) {
    throw 'Analytics SHADOW V2 is not installed. Install Analytics V2 first.'
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ("backup-before-counterfactual-" + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','counterfactual_shadow.py')) {
    $src = Join-Path $app $f
    if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host "[OK] Backup: $backup"

$tmp = Join-Path $env:TEMP 'myshka_counterfactual_shadow'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/7] Downloading counterfactual engine...'
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/counterfactual_shadow.py?v=' + $cacheBust) -OutFile (Join-Path $tmp 'counterfactual_shadow.py')

Write-Host '[2/7] Downloading safe AST patcher...'
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/patch_counterfactual_shadow.py?v=' + $cacheBust) -OutFile (Join-Path $tmp 'patch_counterfactual_shadow.py')

Write-Host '[3/7] Validating downloaded Python files...'
& python -m py_compile (Join-Path $tmp 'counterfactual_shadow.py') (Join-Path $tmp 'patch_counterfactual_shadow.py')
if($LASTEXITCODE -ne 0){ throw 'Downloaded Counterfactual files failed syntax check. Local ASTRA was not modified.' }
Write-Host '[OK] Downloaded files syntax valid.' -ForegroundColor Green

Write-Host '[4/7] Installing observer + API...'
Copy-Item (Join-Path $tmp 'counterfactual_shadow.py') (Join-Path $app 'counterfactual_shadow.py') -Force
try {
    & python (Join-Path $tmp 'patch_counterfactual_shadow.py') $app
    if($LASTEXITCODE -ne 0){ throw "counterfactual patcher failed: $LASTEXITCODE" }

    Push-Location $app
    try {
        $check = @('api.py','counterfactual_shadow.py','analytics_shadow.py')
        foreach($f in @('market_data.py','context_collector.py','telegram_notify.py')){
            if(Test-Path $f){ $check += $f }
        }
        & python -m py_compile @check
        if($LASTEXITCODE -ne 0){ throw "python compile failed after counterfactual patch: $LASTEXITCODE" }
    } finally { Pop-Location }
} catch {
    Copy-Item (Join-Path $backup 'api.py') $apiPath -Force
    $old = Join-Path $backup 'counterfactual_shadow.py'
    if(Test-Path $old) {
        Copy-Item $old (Join-Path $app 'counterfactual_shadow.py') -Force
    } elseif(Test-Path (Join-Path $app 'counterfactual_shadow.py')) {
        Remove-Item (Join-Path $app 'counterfactual_shadow.py') -Force
    }
    Write-Host '[ROLLBACK] Restored pre-counterfactual files.' -ForegroundColor Yellow
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

Write-Host '[7/7] Counterfactual health check...'
if(-not $health.counterfactual_shadow) {
    throw 'ASTRA is healthy but counterfactual_shadow is missing from /health.'
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - COUNTERFACTUAL ANALYTICS SHADOW ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ("ASTRA health: " + $health.status)
if($health.context_collector){
    Write-Host ("Context collector running: " + $health.context_collector.running)
}
if($health.analytics_shadow){
    Write-Host ("Analytics mode: " + $health.analytics_shadow.mode)
}
Write-Host ("Counterfactual mode: " + $health.counterfactual_shadow.mode)
Write-Host ("Counterfactual open: " + $health.counterfactual_shadow.open)
Write-Host ("Counterfactual closed: " + $health.counterfactual_shadow.closed)
Write-Host ("Counterfactual DB: " + $health.counterfactual_shadow.db_path)
Write-Host ("Horizon: " + $health.counterfactual_shadow.horizon_sec + " sec")
Write-Host 'Tracks: EDGE DROP + JEV REJECT'
Write-Host 'Extra Bybit requests: NO'
Write-Host 'Real rejected orders opened: NO'
Write-Host 'Trading decisions changed: NO (SHADOW only)'
Write-Host 'STRICT +0.05% EDGE: preserved'
Write-Host 'Analytics V2 + Context 24/7: preserved'
Write-Host 'Rate-limit + stale-settlement guards: preserved'
Write-Host ''
Write-Host 'Dashboard: Ctrl+F5'
Write-Host "Backup: $backup"
