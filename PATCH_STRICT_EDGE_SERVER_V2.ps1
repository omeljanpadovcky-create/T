$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - STRICT EDGE SERVER PAYLOAD V2 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ''

$bundleCommit = '84ff08f1f2e24b8074515b1da2dc000cdb5b55fb'
$patchUrl = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/' + $bundleCommit + '/astra_strict_edge_v2/patch_strict_edge_server_v2.py'
Write-Host ("Pinned patch: " + $bundleCommit) -ForegroundColor DarkGray

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
    throw 'ASTRA api.py not found. Start ASTRA first.'
}

$api = Join-Path $app 'api.py'
Write-Host ("[OK] ASTRA project: " + $app) -ForegroundColor Green

Write-Host '[1/6] Preflight api.py...'
& python -m py_compile $api
if($LASTEXITCODE -ne 0){ throw 'Current api.py syntax invalid. Nothing changed.' }
Write-Host '[OK] Current api.py syntax valid.' -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ("api_before_strict_edge_server_v2_" + $stamp + ".py")
Copy-Item $api $backup -Force
Write-Host ("[OK] Backup: " + $backup)

$tmp = Join-Path $env:TEMP 'myshka_strict_edge_server_v2'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$patcher = Join-Path $tmp 'patch_strict_edge_server_v2.py'

Write-Host '[2/6] Downloading pinned patcher...'
Invoke-WebRequest -UseBasicParsing -Uri $patchUrl -OutFile $patcher
$txt = Get-Content $patcher -Raw
if($txt -notmatch 'MYSHKA_STRICT_EDGE_PAYLOAD_V2'){
    throw 'Pinned patch verification failed. Local ASTRA was not modified.'
}
& python -m py_compile $patcher
if($LASTEXITCODE -ne 0){ throw 'Downloaded patcher syntax invalid. Local ASTRA was not modified.' }
Write-Host '[OK] Patcher verified.' -ForegroundColor Green

Write-Host '[3/6] Patching server EDGE payload...'
try {
    & python $patcher $api
    if($LASTEXITCODE -ne 0){ throw "patcher failed: $LASTEXITCODE" }
    & python -m py_compile $api
    if($LASTEXITCODE -ne 0){ throw 'api.py compile failed after patch.' }
} catch {
    Copy-Item $backup $api -Force
    Write-Host '[ROLLBACK] api.py restored.' -ForegroundColor Yellow
    throw
}
Write-Host '[OK] api.py patched and compiled.' -ForegroundColor Green

Write-Host '[4/6] Verifying payload semantics in source...'
$apiText = Get-Content $api -Raw
foreach($needle in @(
    'MYSHKA_STRICT_EDGE_PAYLOAD_V2',
    'edge_payload["passed"] = False',
    'edge_payload["reason"] = "strict_edge_buffer"',
    'edge_payload["min_required_net_edge_pct"] = 0.05'
)){
    if($apiText -notmatch [regex]::Escape($needle)){
        Copy-Item $backup $api -Force
        throw ("Source verification failed: " + $needle + ". api.py restored.")
    }
}
Write-Host '[OK] Server will expose strict EDGE DROP as passed=false.' -ForegroundColor Green

Write-Host '[5/6] Rebuilding ASTRA...'
Push-Location $app
try {
    docker compose up -d --build --force-recreate astra
    if($LASTEXITCODE -ne 0){ throw "docker compose failed: $LASTEXITCODE" }
} finally { Pop-Location }

Write-Host '[6/6] Health check...'
$health = $null
for($i=0; $i -lt 45; $i++){
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
        if($health.status -eq 'ok'){ break }
    } catch {}
}
if(-not $health -or $health.status -ne 'ok'){
    docker logs --tail 160 myshka-astra
    throw 'ASTRA did not become healthy after rebuild.'
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - STRICT EDGE SERVER PAYLOAD V2 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ("ASTRA health: " + $health.status)
Write-Host 'STRICT 4/4: Net Edge <= +0.05% => server DROP'
Write-Host 'Server edge.passed on that DROP: False'
Write-Host 'Server edge.reason: strict_edge_buffer'
Write-Host 'Server min_required_net_edge_pct: 0.05'
Write-Host 'TRAIN 3/4 rule: unchanged'
Write-Host 'Risk Intelligence / Analytics / Counterfactual: unchanged'
Write-Host 'Extra Bybit requests: NO'
Write-Host ''
Write-Host 'Dashboard: Ctrl+F5 after the next scan'
Write-Host ("Backup: " + $backup)
