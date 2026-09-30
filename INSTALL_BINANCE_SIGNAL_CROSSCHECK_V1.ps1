$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - BINANCE SIGNAL CROSSCHECK V1 ' -ForegroundColor Yellow
Write-Host ' SHADOW ONLY · MYSHKA <-> BINANCE FUTURES SENTIMENT ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '9557a47943659d772c5be330432c6b31f41105b5'
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
$backup = Join-Path $app ('backup-before-binance-crosscheck-v1-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','binance_signal_crosscheck.py')) {
  $src = Join-Path $app $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_binance_crosscheck_v1'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @{
  'binance_signal_crosscheck.py' = $root + '/astra_binance_crosscheck/binance_signal_crosscheck.py'
  'patch_binance_signal_crosscheck.py' = $root + '/astra_binance_crosscheck/patch_binance_signal_crosscheck.py'
  'selftest_binance_signal_crosscheck.py' = $root + '/astra_binance_crosscheck/selftest_binance_signal_crosscheck.py'
}

Write-Host '[1/8] Downloading pinned bundle...'
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name)
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/8] Python syntax check...'
$py = @(
  (Join-Path $tmp 'binance_signal_crosscheck.py'),
  (Join-Path $tmp 'patch_binance_signal_crosscheck.py'),
  (Join-Path $tmp 'selftest_binance_signal_crosscheck.py')
)
& python -m py_compile @py
if($LASTEXITCODE -ne 0){ throw 'Downloaded Python syntax invalid. Local ASTRA not modified.' }
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[3/8] Running isolated SHADOW self-test...'
Push-Location $tmp
try {
  & python '.\selftest_binance_signal_crosscheck.py'
  if($LASTEXITCODE -ne 0){ throw 'Binance Signal Crosscheck self-test failed. Local ASTRA not modified.' }
} finally { Pop-Location }
Write-Host '[OK] Crosscheck self-test passed.' -ForegroundColor Green

Write-Host '[4/8] Installing module + API patch...'
try {
  Copy-Item (Join-Path $tmp 'binance_signal_crosscheck.py') (Join-Path $app 'binance_signal_crosscheck.py') -Force
  & python (Join-Path $tmp 'patch_binance_signal_crosscheck.py') $app
  if($LASTEXITCODE -ne 0){ throw 'Binance crosscheck API patch failed.' }

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'binance_signal_crosscheck.py'
    if($LASTEXITCODE -ne 0){ throw 'Final ASTRA compile failed.' }
  } finally { Pop-Location }
} catch {
  if(Test-Path (Join-Path $backup 'api.py')){
    Copy-Item (Join-Path $backup 'api.py') (Join-Path $app 'api.py') -Force
  }
  $old = Join-Path $backup 'binance_signal_crosscheck.py'
  $dst = Join-Path $app 'binance_signal_crosscheck.py'
  if(Test-Path $old){ Copy-Item $old $dst -Force }
  elseif(Test-Path $dst){ Remove-Item $dst -Force }
  Write-Host '[ROLLBACK] Restored pre-crosscheck files.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Module installed and api.py compiled.' -ForegroundColor Green

Write-Host '[5/8] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[6/8] Waiting for /health...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok' -and $health.binance_crosscheck){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health check failed.' }
if(-not $health.binance_crosscheck){ throw 'Binance crosscheck missing from /health.' }
Write-Host '[OK] ASTRA health + Binance Crosscheck present.' -ForegroundColor Green

Write-Host '[7/8] Checking authenticated report endpoint...'
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
$report = $null
try {
  $report = Invoke-RestMethod 'http://127.0.0.1:8088/binance-crosscheck/report' -Headers $headers -TimeoutSec 10
} catch {
  throw ('Crosscheck report endpoint failed: ' + $_.Exception.Message)
}
if(-not $report -or $report.status -ne 'ok'){ throw 'Crosscheck report did not return status=ok.' }

Write-Host '[8/8] Summary...'
Write-Host ''
Write-Host '======================================================' -ForegroundColor Green
Write-Host ' READY - BINANCE SIGNAL CROSSCHECK V1 ' -ForegroundColor Green
Write-Host '======================================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Mode: ' + $health.binance_crosscheck.mode)
Write-Host ('Binance period: ' + $health.binance_crosscheck.period)
Write-Host ('Workers: ' + $health.binance_crosscheck.workers)
Write-Host ('Horizons: ' + ($health.binance_crosscheck.horizons_sec -join ',') + ' sec')
Write-Host ('Cached symbols now: ' + $health.binance_crosscheck.cache_symbols)
Write-Host ('DB: ' + $health.binance_crosscheck.db_path)
Write-Host ''
Write-Host 'What happens next:'
Write-Host ' - next ASTRA scans queue Binance snapshots for LONG/SHORT candidates'
Write-Host ' - second/following scans show AGREE / CONFLICT / NEUTRAL'
Write-Host ' - 5m/10m/15m outcomes settle automatically'
Write-Host ' - dashboard reads /binance-crosscheck/report'
Write-Host ''
Write-Host 'Safety invariants:'
Write-Host ' - SHADOW ONLY'
Write-Host ' - does NOT change ENTER/DROP'
Write-Host ' - does NOT create or rescue a signal'
Write-Host ' - public Binance futures sentiment endpoints only'
Write-Host ' - no Binance API key required'
Write-Host ' - LIVE routing added: NO'
Write-Host ('Backup: ' + $backup)
