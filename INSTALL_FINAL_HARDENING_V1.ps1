$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FINAL HARDENING V1 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ''

$bundleCommit = 'da54d4231dd8ace5c48254b7adb1efca837a3395'
$root = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/' + $bundleCommit
Write-Host ('Pinned bundle: ' + $bundleCommit) -ForegroundColor DarkGray

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
$hard = Join-Path $app 'system_hardening.py'

Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green
foreach($required in @('analytics_shadow.py','counterfactual_shadow.py')) {
    if(-not (Test-Path (Join-Path $app $required))){
        throw ('Required module missing: ' + $required)
    }
}

Write-Host '[1/10] Preflight current ASTRA...'
& python -m py_compile $api
if($LASTEXITCODE -ne 0){ throw 'Current api.py syntax invalid. Nothing changed.' }
Write-Host '[OK] Current api.py syntax valid.' -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-final-hardening-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','risk_intelligence_shadow.py','system_hardening.py','selftest_hardening.py','BACKUP_ASTRA_DATA.ps1','RESTORE_ASTRA_DATA.ps1','RUN_ASTRA_SAFE_CHAOS_TESTS.ps1')){
    $src = Join-Path $app $f
    if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Code backup: ' + $backup)

$tmp = Join-Path $env:TEMP 'myshka_final_hardening_v1'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @{
    'risk_intelligence_shadow.py' = $root + '/astra_risk_intelligence_shadow/risk_intelligence_shadow.py'
    'patch_risk_quality_v2.py' = $root + '/astra_risk_intelligence_shadow/patch_risk_quality_v2.py'
    'selftest_quality_v2.py' = $root + '/astra_risk_intelligence_shadow/selftest_quality_v2.py'
    'system_hardening.py' = $root + '/astra_hardening/system_hardening.py'
    'patch_final_hardening.py' = $root + '/astra_hardening/patch_final_hardening.py'
    'selftest_hardening.py' = $root + '/astra_hardening/selftest_hardening.py'
    'BACKUP_ASTRA_DATA.ps1' = $root + '/astra_hardening/BACKUP_ASTRA_DATA.ps1'
    'RESTORE_ASTRA_DATA.ps1' = $root + '/astra_hardening/RESTORE_ASTRA_DATA.ps1'
    'RUN_ASTRA_SAFE_CHAOS_TESTS.ps1' = $root + '/astra_hardening/RUN_ASTRA_SAFE_CHAOS_TESTS.ps1'
}

Write-Host '[2/10] Downloading pinned final bundle...'
foreach($name in $downloads.Keys){
    Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name)
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[3/10] Verifying bundle markers + syntax...'
$riskText = Get-Content (Join-Path $tmp 'risk_intelligence_shadow.py') -Raw
$hardText = Get-Content (Join-Path $tmp 'system_hardening.py') -Raw
$hardPatchText = Get-Content (Join-Path $tmp 'patch_final_hardening.py') -Raw
if($riskText -notmatch 'def quality_report' -or $riskText -notmatch 'decision_blackbox'){
    throw 'Risk Quality V2 bundle verification failed.'
}
if($hardText -notmatch 'def observe_results' -or $hardText -notmatch 'config_versions' -or $hardText -notmatch 'timestamp_alignment'){
    throw 'Final Hardening bundle verification failed.'
}
if($hardPatchText -notmatch 'MYSHKA_FINAL_HARDENING_V1'){
    throw 'Final Hardening patcher marker missing.'
}

$pyFiles = @(
    (Join-Path $tmp 'risk_intelligence_shadow.py'),
    (Join-Path $tmp 'patch_risk_quality_v2.py'),
    (Join-Path $tmp 'selftest_quality_v2.py'),
    (Join-Path $tmp 'system_hardening.py'),
    (Join-Path $tmp 'patch_final_hardening.py'),
    (Join-Path $tmp 'selftest_hardening.py')
)
& python -m py_compile @pyFiles
if($LASTEXITCODE -ne 0){ throw 'Downloaded Python bundle syntax invalid.' }

foreach($ps in @('BACKUP_ASTRA_DATA.ps1','RESTORE_ASTRA_DATA.ps1','RUN_ASTRA_SAFE_CHAOS_TESTS.ps1')){
    $tokens=$null
    $errs=$null
    [void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path $tmp $ps),[ref]$tokens,[ref]$errs)
    if($errs.Count -gt 0){
        $errs | Format-Table -AutoSize
        throw ('PowerShell syntax invalid: ' + $ps)
    }
}
Write-Host '[OK] Python + PowerShell syntax valid.' -ForegroundColor Green

Write-Host '[4/10] Running Risk Quality V2 isolated self-test...'
$qLog = Join-Path $tmp 'quality-selftest.log'
$py = (Get-Command python).Source
$cmd = ('cd /d "' + $tmp + '" && "' + $py + '" "selftest_quality_v2.py" > "' + $qLog + '" 2>&1')
& $env:ComSpec /d /c $cmd
$qExit = $LASTEXITCODE
$qOut = if(Test-Path $qLog){ Get-Content $qLog -Raw } else { '' }
if($qOut){ Write-Host $qOut }
if($qExit -ne 0){ throw ('Risk Quality V2 self-test failed. Local ASTRA not modified. ' + $qOut) }
Write-Host '[OK] Risk Quality V2 self-test passed.' -ForegroundColor Green

Write-Host '[5/10] Running Final Hardening + safe-chaos self-test...'
$hLog = Join-Path $tmp 'hardening-selftest.log'
$cmd = ('cd /d "' + $tmp + '" && "' + $py + '" "selftest_hardening.py" > "' + $hLog + '" 2>&1')
& $env:ComSpec /d /c $cmd
$hExit = $LASTEXITCODE
$hOut = if(Test-Path $hLog){ Get-Content $hLog -Raw } else { '' }
if($hOut){ Write-Host $hOut }
if($hExit -ne 0){ throw ('Final Hardening self-test failed. Local ASTRA not modified. ' + $hOut) }
Write-Host '[OK] Hardening safe-chaos self-test passed.' -ForegroundColor Green

Write-Host '[6/10] Installing backend modules + API endpoints...'
try {
    Copy-Item (Join-Path $tmp 'risk_intelligence_shadow.py') $risk -Force
    Copy-Item (Join-Path $tmp 'system_hardening.py') $hard -Force
    Copy-Item (Join-Path $tmp 'selftest_hardening.py') (Join-Path $app 'selftest_hardening.py') -Force

    & python (Join-Path $tmp 'patch_risk_quality_v2.py') $app
    if($LASTEXITCODE -ne 0){ throw ('Risk Quality patch failed: ' + $LASTEXITCODE) }

    & python (Join-Path $tmp 'patch_final_hardening.py') $app
    if($LASTEXITCODE -ne 0){ throw ('Final Hardening patch failed: ' + $LASTEXITCODE) }

    foreach($ps in @('BACKUP_ASTRA_DATA.ps1','RESTORE_ASTRA_DATA.ps1','RUN_ASTRA_SAFE_CHAOS_TESTS.ps1')){
        Copy-Item (Join-Path $tmp $ps) (Join-Path $app $ps) -Force
        Copy-Item (Join-Path $tmp $ps) (Join-Path $env:USERPROFILE ('Downloads\' + $ps)) -Force
    }

    Push-Location $app
    try {
        $check = @('api.py','risk_intelligence_shadow.py','system_hardening.py','analytics_shadow.py','counterfactual_shadow.py','selftest_hardening.py')
        foreach($f in @('market_data.py','context_collector.py','telegram_notify.py')){
            if(Test-Path $f){ $check += $f }
        }
        & python -m py_compile @check
        if($LASTEXITCODE -ne 0){ throw ('Final project compile failed: ' + $LASTEXITCODE) }
    } finally { Pop-Location }
} catch {
    Copy-Item (Join-Path $backup 'api.py') $api -Force
    foreach($name in @('risk_intelligence_shadow.py','system_hardening.py','selftest_hardening.py','BACKUP_ASTRA_DATA.ps1','RESTORE_ASTRA_DATA.ps1','RUN_ASTRA_SAFE_CHAOS_TESTS.ps1')){
        $old = Join-Path $backup $name
        $dst = Join-Path $app $name
        if(Test-Path $old){ Copy-Item $old $dst -Force }
        elseif(Test-Path $dst){ Remove-Item $dst -Force }
    }
    Write-Host '[ROLLBACK] Restored pre-hardening project files.' -ForegroundColor Yellow
    throw
}
Write-Host '[OK] Backend modules/endpoints/scripts installed.' -ForegroundColor Green

Write-Host '[7/10] Rebuilding ASTRA...'
Push-Location $app
try {
    docker compose up -d --build --force-recreate astra
    if($LASTEXITCODE -ne 0){ throw ('docker compose failed: ' + $LASTEXITCODE) }
} finally { Pop-Location }

Write-Host '[8/10] Waiting for ASTRA health...'
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
    throw 'ASTRA did not become healthy after final hardening.'
}
if(-not $health.hardening){
    throw 'ASTRA is healthy but hardening status is missing from /health.'
}
Write-Host '[OK] ASTRA health + hardening health present.' -ForegroundColor Green

Write-Host '[9/10] Verifying diagnostic endpoint...'
$headers = @{}
$token = $env:MYSHKA_TOKEN
if(-not $token){
    $envFile = Join-Path $app '.env'
    if(Test-Path $envFile){
        $line = Get-Content $envFile | Where-Object { $_ -match '^MYSHKA_TOKEN=' } | Select-Object -First 1
        if($line){ $token = ($line -replace '^MYSHKA_TOKEN=','').Trim().Trim('"').Trim("'") }
    }
}
if($token){ $headers['X-MYSHKA-Token'] = $token }

$hardening = $null
$protected = $false
try {
    $hardening = Invoke-RestMethod 'http://127.0.0.1:8088/hardening/status' -Headers $headers -TimeoutSec 8
} catch {
    if($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -in @(401,403)){
        $protected = $true
        Write-Host '[OK] Hardening endpoint is token-protected; dashboard will use configured token.' -ForegroundColor Green
    } else {
        throw 'Hardening endpoint did not answer.'
    }
}
if(-not $protected -and $hardening.status -ne 'ok'){
    throw 'Hardening endpoint returned non-ok status.'
}

Write-Host '[10/10] Final integrity summary...'
Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - FINAL HARDENING V1 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Hardening mode: ' + $health.hardening.mode)
Write-Host ('Hardening DB: ' + $health.hardening.db_path)
if(-not $protected -and $hardening){
    if($hardening.data_quality){
        Write-Host ('Data quality: ' + $hardening.data_quality.ok_n + '/' + $hardening.data_quality.total + ' · ' + $hardening.data_quality.state)
    } else {
        Write-Host 'Data quality: WARMING · first normal scan will populate it'
    }
    if($hardening.config_current){
        Write-Host ('Config version: ' + $hardening.config_current.version + ' · ' + $hardening.config_current.fingerprint)
    } else {
        Write-Host 'Config version: WARMING · first normal scan will create v1.0'
    }
    Write-Host ('Reconciliation: ' + $hardening.reconciliation.state + ' · use dashboard Reconcile now for Bybit/Freqtrade snapshot')
}
Write-Host ''
Write-Host 'Installed:'
Write-Host ' - PAPER execution reconciliation + Analytics open-position check'
Write-Host ' - manual read-only Bybit/Freqtrade reconciliation'
Write-Host ' - live-safe SQLite backup + explicit restore'
Write-Host ' - SAFE chaos simulation tests'
Write-Host ' - versioned config fingerprints'
Write-Host ' - data quality: universe, duplicates, prices, bid/ask, spread, candles, context freshness, timestamp alignment, decision invariants'
Write-Host ''
Write-Host 'Trading decisions changed: NO'
Write-Host 'Live order routing added: NO'
Write-Host 'Extra market requests per normal scan: NO'
Write-Host 'STRICT +0.05% EDGE: preserved'
Write-Host 'PAPER mode: preserved'
Write-Host ''
Write-Host 'Tools copied to Downloads:'
Write-Host ' BACKUP_ASTRA_DATA.ps1'
Write-Host ' RESTORE_ASTRA_DATA.ps1'
Write-Host ' RUN_ASTRA_SAFE_CHAOS_TESTS.ps1'
Write-Host ''
Write-Host 'Dashboard: Ctrl+F5 after install / next normal scan'
Write-Host ('Code backup: ' + $backup)
