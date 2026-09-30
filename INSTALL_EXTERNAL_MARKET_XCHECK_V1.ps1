$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - EXTERNAL MARKET XCHECK V1 ' -ForegroundColor Yellow
Write-Host ' INVESTING TECH + MACRO CROSS-MARKET + FORWARD SHADOW ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '93c2913197638cb404d265acddeaad1cee41a61f'
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
if (-not $app -or -not (Test-Path (Join-Path $app 'api.py'))) {
  throw 'ASTRA project folder not found.'
}
Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-external-market-xcheck-v1-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','telegram_notify.py','external_market_xcheck.py')) {
  $src = Join-Path $app $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_external_market_xcheck_v1'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @{
  'external_market_xcheck.py' = $root + '/astra_external_market_xcheck/external_market_xcheck.py'
  'patch_external_market_xcheck.py' = $root + '/astra_external_market_xcheck/patch_external_market_xcheck.py'
  'selftest_external_market_xcheck.py' = $root + '/astra_external_market_xcheck/selftest_external_market_xcheck.py'
}

Write-Host '[1/9] Downloading pinned bundle...'
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name)
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/9] Python syntax check...'
$py = @(
  (Join-Path $tmp 'external_market_xcheck.py'),
  (Join-Path $tmp 'patch_external_market_xcheck.py'),
  (Join-Path $tmp 'selftest_external_market_xcheck.py')
)
& python -m py_compile @py
if($LASTEXITCODE -ne 0){ throw 'Downloaded Python syntax invalid. Local ASTRA not modified.' }
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[3/9] Running isolated SHADOW self-test...'
Push-Location $tmp
try {
  & python '.\selftest_external_market_xcheck.py'
  if($LASTEXITCODE -ne 0){ throw 'External Market XCheck self-test failed. Local ASTRA not modified.' }
} finally { Pop-Location }
Write-Host '[OK] Self-test passed.' -ForegroundColor Green

Write-Host '[4/9] Installing module + API + Telegram patch...'
try {
  Copy-Item (Join-Path $tmp 'external_market_xcheck.py') (Join-Path $app 'external_market_xcheck.py') -Force
  & python (Join-Path $tmp 'patch_external_market_xcheck.py') $app
  if($LASTEXITCODE -ne 0){ throw 'External xcheck patch failed.' }

  Push-Location $app
  try {
    $compileFiles = @('api.py','external_market_xcheck.py')
    if(Test-Path 'telegram_notify.py'){ $compileFiles += 'telegram_notify.py' }
    & python -m py_compile @compileFiles
    if($LASTEXITCODE -ne 0){ throw 'Final ASTRA compile failed.' }
  } finally { Pop-Location }
} catch {
  foreach($f in @('api.py','telegram_notify.py','external_market_xcheck.py')) {
    $old = Join-Path $backup $f
    $dst = Join-Path $app $f
    if(Test-Path $old){ Copy-Item $old $dst -Force }
    elseif($f -eq 'external_market_xcheck.py' -and (Test-Path $dst)){ Remove-Item $dst -Force }
  }
  Write-Host '[ROLLBACK] Restored pre-xcheck files.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Module installed and Python compiled.' -ForegroundColor Green

Write-Host '[5/9] Verifying safety markers...'
$apiText = Get-Content (Join-Path $app 'api.py') -Raw
$modText = Get-Content (Join-Path $app 'external_market_xcheck.py') -Raw
if($apiText -notmatch 'MYSHKA_EXTERNAL_MARKET_XCHECK_V1'){ throw 'API marker missing.' }
if($modText -notmatch 'Never changes r\["action"\]'){ throw 'Safety marker missing.' }
if($modText -match 'create_order|forceenter'){ throw 'Unexpected order-routing text found in SHADOW module.' }
Write-Host '[OK] SHADOW-only safety checks passed.' -ForegroundColor Green

Write-Host '[6/9] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[7/9] Waiting for /health...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok' -and $health.external_market_xcheck){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health check failed.' }
if(-not $health.external_market_xcheck){ throw 'External Market XCheck missing from /health.' }
Write-Host '[OK] ASTRA health + External Market XCheck present.' -ForegroundColor Green

Write-Host '[8/9] Checking authenticated report endpoint...'
$token = $null
try {
  $token = (docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
    Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
    Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
} catch {}
if(-not $token){
  $envFile = Join-Path $app '.env'
  if(Test-Path $envFile){
    $line = Get-Content $envFile | Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } | Select-Object -First 1
    if($line){ $token = ($line -replace '^MYSHKA_BRIDGE_TOKEN=','').Trim().Trim('"').Trim("'") }
  }
}
$headers = @{}
if($token){ $headers['X-MYSHKA-TOKEN'] = $token }

$report = Invoke-RestMethod 'http://127.0.0.1:8088/external-xcheck/report' -Headers $headers -TimeoutSec 10
if(-not $report -or $report.status -ne 'ok'){ throw 'External xcheck report did not return status=ok.' }
Write-Host '[OK] /external-xcheck/report = ok' -ForegroundColor Green

Write-Host '[9/9] Summary...'
Write-Host ''
Write-Host '======================================================' -ForegroundColor Green
Write-Host ' READY - EXTERNAL MARKET XCHECK V1 ' -ForegroundColor Green
Write-Host '======================================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Mode: ' + $health.external_market_xcheck.mode)
Write-Host ('Investing symbols: ' + ($health.external_market_xcheck.investing_supported_symbols -join ', '))
Write-Host ('Macro assets: ' + ($health.external_market_xcheck.macro_assets -join ', '))
Write-Host ('Horizons: ' + ($health.external_market_xcheck.horizons_sec -join ', ') + ' sec')
Write-Host ('DB: ' + $health.external_market_xcheck.db_path)
Write-Host ''
Write-Host 'Installed:'
Write-Host ' - Investing.com TECH XCheck: 30m / 1h / 5h / 1d'
Write-Host ' - Macro Cross-Market: Nasdaq100 / DXY / Gold / WTI / VIX'
Write-Host ' - Combined states: BOTH_AGREE / BOTH_CONFLICT / MIXED / PARTIAL / NEUTRAL'
Write-Host ' - Forward outcomes: 5m / 10m / 15m'
Write-Host ' - Cluster-adjusted n / Avg NET / PF'
Write-Host ' - Per-pair attribution'
Write-Host ' - Telegram INVESTING XCHECK + MACRO SHADOW lines'
Write-Host ''
Write-Host 'Research rule:'
Write-Host ' - cluster_n < 30 = COLD'
Write-Host ' - cluster_n >= 30 = WATCH only'
Write-Host ' - confirm on NEW independent forward clusters before any gate change'
Write-Host ''
Write-Host 'Safety invariants:'
Write-Host ' - SHADOW ONLY'
Write-Host ' - EDGE 0.05 unchanged'
Write-Host ' - JEV / Evidence / Guard / Adaptive unchanged'
Write-Host ' - PAPER decisions unchanged'
Write-Host ' - Freqtrade routing unchanged'
Write-Host ' - Real-money execution unchanged / disabled'
Write-Host ('Backup: ' + $backup)
Write-Host ''
Write-Host 'Note: first directional scans can show NO_DATA for a short warm-up until external caches fill.'
