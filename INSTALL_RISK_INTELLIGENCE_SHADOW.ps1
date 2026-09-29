$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - RISK INTELLIGENCE SHADOW ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ''

$base = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/main/astra_risk_intelligence_shadow'
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
    throw 'Current api.py is not valid. Risk Intelligence installer did not modify anything.'
}
Write-Host '[OK] Current api.py syntax valid.' -ForegroundColor Green

foreach($required in @('analytics_shadow.py','counterfactual_shadow.py')) {
    if(-not (Test-Path (Join-Path $app $required))) {
        throw ("Required module missing: " + $required + ". Install Analytics V2 + Counterfactual SHADOW first.")
    }
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ("backup-before-risk-intelligence-" + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','risk_intelligence_shadow.py')) {
    $src = Join-Path $app $f
    if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host "[OK] Backup: $backup"

$tmp = Join-Path $env:TEMP 'myshka_risk_intelligence_shadow'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/8] Downloading Risk Intelligence engine...'
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/risk_intelligence_shadow.py?v=' + $cacheBust) -OutFile (Join-Path $tmp 'risk_intelligence_shadow.py')

Write-Host '[2/8] Downloading safe patcher + runtime self-test...'
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/patch_risk_intelligence_shadow.py?v=' + $cacheBust) -OutFile (Join-Path $tmp 'patch_risk_intelligence_shadow.py')
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/selftest_risk_intelligence.py?v=' + $cacheBust) -OutFile (Join-Path $tmp 'selftest_risk_intelligence.py')

Write-Host '[3/8] Validating downloaded Python files...'
& python -m py_compile (Join-Path $tmp 'risk_intelligence_shadow.py') (Join-Path $tmp 'patch_risk_intelligence_shadow.py') (Join-Path $tmp 'selftest_risk_intelligence.py')
if($LASTEXITCODE -ne 0){ throw 'Downloaded Risk Intelligence files failed syntax check. Local ASTRA was not modified.' }
Write-Host '[OK] Downloaded files syntax valid.' -ForegroundColor Green

Write-Host '[4/8] Running isolated Risk Intelligence runtime self-test against real Analytics V2 schema...'
$selftestOutput = & python (Join-Path $tmp 'selftest_risk_intelligence.py') $app 2>&1
$selftestExit = $LASTEXITCODE
$selftestOutput | ForEach-Object { Write-Host $_ }
if($selftestExit -ne 0){ throw 'Risk Intelligence runtime self-test failed. Local ASTRA was not modified.' }
Write-Host '[OK] Runtime self-test passed.' -ForegroundColor Green

Write-Host '[5/8] Installing SHADOW observer + API...'
Copy-Item (Join-Path $tmp 'risk_intelligence_shadow.py') (Join-Path $app 'risk_intelligence_shadow.py') -Force
try {
    & python (Join-Path $tmp 'patch_risk_intelligence_shadow.py') $app
    if($LASTEXITCODE -ne 0){ throw "Risk Intelligence patcher failed: $LASTEXITCODE" }

    Push-Location $app
    try {
        $check = @('api.py','risk_intelligence_shadow.py','analytics_shadow.py','counterfactual_shadow.py')
        foreach($f in @('market_data.py','context_collector.py','telegram_notify.py')){
            if(Test-Path $f){ $check += $f }
        }
        & python -m py_compile @check
        if($LASTEXITCODE -ne 0){ throw "python compile failed after Risk Intelligence patch: $LASTEXITCODE" }
    } finally { Pop-Location }
} catch {
    Copy-Item (Join-Path $backup 'api.py') $apiPath -Force
    $old = Join-Path $backup 'risk_intelligence_shadow.py'
    if(Test-Path $old) {
        Copy-Item $old (Join-Path $app 'risk_intelligence_shadow.py') -Force
    } elseif(Test-Path (Join-Path $app 'risk_intelligence_shadow.py')) {
        Remove-Item (Join-Path $app 'risk_intelligence_shadow.py') -Force
    }
    Write-Host '[ROLLBACK] Restored pre-Risk-Intelligence files.' -ForegroundColor Yellow
    throw
}
Write-Host '[OK] Final Python syntax valid.' -ForegroundColor Green

Write-Host '[6/8] Rebuilding ASTRA...'
Push-Location $app
try {
    docker compose up -d --build --force-recreate astra
    if($LASTEXITCODE -ne 0){ throw "docker compose failed: $LASTEXITCODE" }
} finally { Pop-Location }

Write-Host '[7/8] Waiting for ASTRA health...'
$health = $null
for($i=0; $i -lt 45; $i++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
        if($health.status -eq 'ok'){ break }
    } catch {}
}
if(-not $health -or $health.status -ne 'ok') {
    docker logs --tail 180 myshka-astra
    throw 'ASTRA did not become healthy.'
}

Write-Host '[8/8] Risk Intelligence health check...'
if(-not $health.risk_intelligence_shadow) {
    throw 'ASTRA is healthy but risk_intelligence_shadow is missing from /health.'
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - RISK INTELLIGENCE SHADOW ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ("ASTRA health: " + $health.status)
if($health.context_collector){ Write-Host ("Context collector running: " + $health.context_collector.running) }
if($health.analytics_shadow){ Write-Host ("Analytics mode: " + $health.analytics_shadow.mode) }
if($health.counterfactual_shadow){ Write-Host ("Counterfactual mode: " + $health.counterfactual_shadow.mode) }
Write-Host ("Risk Intelligence mode: " + $health.risk_intelligence_shadow.mode)
Write-Host ("Risk Intelligence open: " + $health.risk_intelligence_shadow.open)
Write-Host ("Risk Intelligence closed: " + $health.risk_intelligence_shadow.closed)
Write-Host ("Risk Intelligence DB: " + $health.risk_intelligence_shadow.db_path)
Write-Host ("Horizon: " + $health.risk_intelligence_shadow.horizon_sec + " sec")
Write-Host ''
Write-Host 'SHADOW modules:'
Write-Host ' - Context Veto 2.0 readiness'
Write-Host ' - Loss-streak guard'
Write-Host ' - Pair cooldown / blacklist'
Write-Host ' - Adaptive EDGE by pair + regime'
Write-Host ' - BTC market filter'
Write-Host ' - OI + Price divergence'
Write-Host ' - Funding extreme guard'
Write-Host ' - Correlation crowding'
Write-Host ' - Volatility shock'
Write-Host ' - Spread / cost history'
Write-Host ' - JEV post-mortem'
Write-Host ' - A/B EDGE 0.05 / 0.10 / 0.15 / 0.20'
Write-Host ' - Confidence score 0..100'
Write-Host ''
Write-Host 'Extra Bybit requests: NO'
Write-Host 'Trading decisions changed: NO (SHADOW only)'
Write-Host 'STRICT +0.05% EDGE: preserved'
Write-Host 'Analytics V2 + Counterfactual + Context 24/7: preserved'
Write-Host 'Rate-limit + stale-settlement guards: preserved'
Write-Host ''
Write-Host 'Dashboard: Ctrl+F5'
Write-Host "Backup: $backup"
