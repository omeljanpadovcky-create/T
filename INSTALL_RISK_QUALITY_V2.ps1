$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - RISK QUALITY CONTROL V2 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ''

$bundleCommit = 'a1e1a312b6ca1fc62b3b55e1dfa788adb1f3a181'
$base = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/' + $bundleCommit + '/astra_risk_intelligence_shadow'
Write-Host ("Pinned bundle: " + $bundleCommit) -ForegroundColor DarkGray

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
    throw 'ASTRA project folder not found. Start Docker + ASTRA first.'
}

$api = Join-Path $app 'api.py'
$risk = Join-Path $app 'risk_intelligence_shadow.py'

Write-Host ("[OK] ASTRA project: " + $app) -ForegroundColor Green
if(-not (Test-Path $risk)){ throw 'risk_intelligence_shadow.py missing. Install Risk Intelligence SHADOW first.' }

Write-Host '[1/8] Preflight current Python...'
& python -m py_compile $api $risk
if($LASTEXITCODE -ne 0){ throw 'Current ASTRA Python invalid. Nothing changed.' }
Write-Host '[OK] Current Python syntax valid.' -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ("backup-before-risk-quality-v2-" + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item $api (Join-Path $backup 'api.py') -Force
Copy-Item $risk (Join-Path $backup 'risk_intelligence_shadow.py') -Force
Write-Host ("[OK] Backup: " + $backup)

$tmp = Join-Path $env:TEMP 'myshka_risk_quality_v2'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$engine = Join-Path $tmp 'risk_intelligence_shadow.py'
$patcher = Join-Path $tmp 'patch_risk_quality_v2.py'
$selftest = Join-Path $tmp 'selftest_quality_v2.py'

Write-Host '[2/8] Downloading pinned Quality V2 bundle...'
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/risk_intelligence_shadow.py') -OutFile $engine
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/patch_risk_quality_v2.py') -OutFile $patcher
Invoke-WebRequest -UseBasicParsing -Uri ($base + '/selftest_quality_v2.py') -OutFile $selftest

$engineText = Get-Content $engine -Raw
$patchText = Get-Content $patcher -Raw
if($engineText -notmatch 'decision_blackbox' -or $engineText -notmatch 'def quality_report' -or $engineText -notmatch 'def replay'){
    throw 'Quality V2 engine freshness verification failed. Local ASTRA was not modified.'
}
if($patchText -notmatch 'MYSHKA_RISK_QUALITY_V2'){
    throw 'Quality V2 patcher freshness verification failed. Local ASTRA was not modified.'
}
Write-Host '[OK] Bundle markers verified.' -ForegroundColor Green

Write-Host '[3/8] Compiling downloaded bundle...'
& python -m py_compile $engine $patcher $selftest
if($LASTEXITCODE -ne 0){ throw 'Quality V2 bundle syntax check failed. Local ASTRA was not modified.' }
Write-Host '[OK] Bundle syntax valid.' -ForegroundColor Green

Write-Host '[4/8] Running isolated runtime self-test...'
$selftestLog = Join-Path $tmp 'selftest.log'
$py = (Get-Command python).Source
$cmdLine = ('"' + $py + '" "' + $selftest + '" > "' + $selftestLog + '" 2>&1')
& $env:ComSpec /d /c $cmdLine
$selftestExit = $LASTEXITCODE
$selftestOutput = if(Test-Path $selftestLog){ Get-Content $selftestLog -Raw } else { '' }
if($selftestOutput){ Write-Host $selftestOutput }
if($selftestExit -ne 0){
    throw ("Risk Quality V2 runtime self-test failed. Local ASTRA was not modified.`n--- PYTHON SELFTEST ---`n" + $selftestOutput)
}
Write-Host '[OK] Runtime self-test passed.' -ForegroundColor Green

Write-Host '[5/8] Installing Quality V2 engine + read-only endpoints...'
Copy-Item $engine $risk -Force
try {
    & python $patcher $app
    if($LASTEXITCODE -ne 0){ throw "API patcher failed: $LASTEXITCODE" }

    Push-Location $app
    try {
        $check = @('api.py','risk_intelligence_shadow.py','analytics_shadow.py','counterfactual_shadow.py')
        foreach($f in @('market_data.py','context_collector.py','telegram_notify.py')){
            if(Test-Path $f){ $check += $f }
        }
        & python -m py_compile @check
        if($LASTEXITCODE -ne 0){ throw "Final compile failed: $LASTEXITCODE" }
    } finally { Pop-Location }
} catch {
    Copy-Item (Join-Path $backup 'api.py') $api -Force
    Copy-Item (Join-Path $backup 'risk_intelligence_shadow.py') $risk -Force
    Write-Host '[ROLLBACK] Restored pre-Quality-V2 files.' -ForegroundColor Yellow
    throw
}
Write-Host '[OK] Backend Quality V2 installed and compiled.' -ForegroundColor Green

Write-Host '[6/8] Rebuilding ASTRA...'
Push-Location $app
try {
    docker compose up -d --build --force-recreate astra
    if($LASTEXITCODE -ne 0){ throw "docker compose failed: $LASTEXITCODE" }
} finally { Pop-Location }

Write-Host '[7/8] Waiting for ASTRA health...'
$health = $null
for($i=0; $i -lt 45; $i++){
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
        if($health.status -eq 'ok'){ break }
    } catch {}
}
if(-not $health -or $health.status -ne 'ok'){
    docker logs --tail 180 myshka-astra
    throw 'ASTRA did not become healthy.'
}

Write-Host '[8/8] Verifying Quality + Replay endpoints...'
try {
    $quality = Invoke-RestMethod 'http://127.0.0.1:8088/risk-intelligence/quality' -TimeoutSec 8
    $replay = Invoke-RestMethod 'http://127.0.0.1:8088/risk-intelligence/replay?limit=1' -TimeoutSec 8
} catch {
    throw 'ASTRA is healthy but Quality V2 endpoints did not answer. If MYSHKA token is required, open dashboard and verify there.'
}
if($quality.status -ne 'ok' -or $replay.status -ne 'ok'){
    throw 'Quality V2 endpoint verification returned non-ok status.'
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - RISK QUALITY CONTROL V2 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ("ASTRA health: " + $health.status)
Write-Host ("State integrity: " + $quality.watchdog.ok_n + "/" + $quality.watchdog.total)
Write-Host ("Guard matrix rows: " + $quality.guard_effectiveness.Count)
Write-Host ("Confidence bins: " + $quality.confidence_calibration.Count)
Write-Host ("Black Box snapshots: " + $quality.blackbox_count)
Write-Host ("Drift state: " + $quality.drift.state)
Write-Host ''
Write-Host 'Added:'
Write-Host ' - Decision Replay / Black Box'
Write-Host ' - Guard Effectiveness Matrix'
Write-Host ' - Confidence calibration'
Write-Host ' - Position / settlement watchdog'
Write-Host ' - Promotion Gate'
Write-Host ' - Drift detector'
Write-Host ''
Write-Host 'Trading decisions changed: NO'
Write-Host 'Automatic guard activation: NO'
Write-Host 'Extra Bybit requests: NO'
Write-Host 'STRICT +0.05% EDGE: preserved'
Write-Host 'Analytics / Counterfactual / Risk Intelligence: preserved'
Write-Host ''
Write-Host 'Dashboard: Ctrl+F5'
Write-Host ("Backup: " + $backup)
