$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '============================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - EXTERNAL MARKET SHADOW V1 ' -ForegroundColor Yellow
Write-Host ' INVESTING XCHECK + MACRO + FORWARD ATTRIBUTION · SHADOW ONLY ' -ForegroundColor Yellow
Write-Host '============================================================' -ForegroundColor Cyan

$bundleCommit = '7e773f21306b8c21214817ce4fbd31b58a33daf9'
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
if (-not (Test-Path (Join-Path $app 'telegram_notify.py'))) {
  throw 'telegram_notify.py not found.'
}
Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-external-market-shadow-v1-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null

foreach($f in @('api.py','telegram_notify.py','external_market_shadow.py')) {
  $src = Join-Path $app $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_external_market_shadow_v1'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @{
  'external_market_shadow.py' = $root + '/astra_external_market_shadow/external_market_shadow.py'
  'patch_external_market_shadow.py' = $root + '/astra_external_market_shadow/patch_external_market_shadow.py'
  'selftest_external_market_shadow.py' = $root + '/astra_external_market_shadow/selftest_external_market_shadow.py'
}

Write-Host '[1/8] Downloading pinned bundle...'
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name)
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/8] Python syntax check...'
$py = @(
  (Join-Path $tmp 'external_market_shadow.py'),
  (Join-Path $tmp 'patch_external_market_shadow.py'),
  (Join-Path $tmp 'selftest_external_market_shadow.py')
)
& python -m py_compile @py
if($LASTEXITCODE -ne 0){ throw 'Downloaded Python syntax invalid. Local ASTRA not modified.' }
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[3/8] Running isolated SHADOW self-test...'
Push-Location $tmp
try {
  & python '.\selftest_external_market_shadow.py'
  if($LASTEXITCODE -ne 0){ throw 'External Market Shadow self-test failed. Local ASTRA not modified.' }
} finally { Pop-Location }
Write-Host '[OK] External Market Shadow self-test passed.' -ForegroundColor Green

Write-Host '[4/8] Installing module + API + Telegram patches...'
try {
  Copy-Item (Join-Path $tmp 'external_market_shadow.py') (Join-Path $app 'external_market_shadow.py') -Force
  & python (Join-Path $tmp 'patch_external_market_shadow.py') $app
  if($LASTEXITCODE -ne 0){ throw 'External Market patch failed.' }

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'telegram_notify.py' 'external_market_shadow.py'
    if($LASTEXITCODE -ne 0){ throw 'Final ASTRA compile failed.' }
  } finally { Pop-Location }
} catch {
  foreach($f in @('api.py','telegram_notify.py','external_market_shadow.py')) {
    $old = Join-Path $backup $f
    $dst = Join-Path $app $f
    if(Test-Path $old){ Copy-Item $old $dst -Force }
    elseif($f -eq 'external_market_shadow.py' -and (Test-Path $dst)){ Remove-Item $dst -Force }
  }
  Write-Host '[ROLLBACK] Restored pre-install files.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Module installed and Python compile passed.' -ForegroundColor Green

Write-Host '[5/8] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[6/8] Waiting for ASTRA health...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok' -and $health.external_market_shadow){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health check failed.' }
if(-not $health.external_market_shadow){ throw 'External Market Shadow missing from /health.' }
Write-Host '[OK] ASTRA health + External Market Shadow present.' -ForegroundColor Green

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
  $report = Invoke-RestMethod 'http://127.0.0.1:8088/external-market/report' -Headers $headers -TimeoutSec 10
} catch {
  throw ('External Market report endpoint failed: ' + $_.Exception.Message)
}
if(-not $report -or $report.status -ne 'ok'){ throw 'External Market report did not return status=ok.' }
Write-Host '[OK] /external-market/report status=ok' -ForegroundColor Green

Write-Host '[8/8] Safety / research summary...'
Write-Host ''
Write-Host '============================================================' -ForegroundColor Green
Write-Host ' READY - EXTERNAL MARKET SHADOW V1 ' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Mode: ' + $health.external_market_shadow.mode)
Write-Host ('Investing cache symbols: ' + $health.external_market_shadow.investing_cached_symbols)
Write-Host ('Macro cache ready: ' + $health.external_market_shadow.macro_cached)
Write-Host ('Horizons: ' + ($health.external_market_shadow.horizons_sec -join ',') + ' sec')
Write-Host ('DB: ' + $health.external_market_shadow.db_path)
Write-Host ''
Write-Host 'Installed:'
Write-Host ' - Investing.com technical XCHECK (30m / 1h / 5h / 1d)'
Write-Host ' - Macro SHADOW: Nasdaq 100 / DXY / Gold / WTI / VIX'
Write-Host ' - Combined state: BOTH_AGREE / BOTH_CONFLICT / MIXED / PARTIAL / NO_DATA'
Write-Host ' - 5m / 10m / 15m forward outcomes'
Write-Host ' - cluster-adjusted n / avg NET / PF'
Write-Host ' - JEV APPROVE x TECH>=3 anchor'
Write-Host ' - pair attribution'
Write-Host ' - positive + toxic clusters shown simultaneously'
Write-Host ' - Telegram INV XCHECK + MACRO SHADOW + EXT COMBINED'
Write-Host ''
Write-Host 'Research rule:'
Write-Host ' - cluster_n=30 => WATCH only'
Write-Host ' - require 30-50 NEW independent clusters for confirmation review'
Write-Host ' - no automatic gate activation'
Write-Host ''
Write-Host 'Safety invariants:'
Write-Host ' - SHADOW ONLY'
Write-Host ' - EDGE 0.05 unchanged'
Write-Host ' - PAPER decisions unchanged'
Write-Host ' - Freqtrade routing unchanged'
Write-Host ' - real-money execution unchanged / disabled'
Write-Host ' - source failure => NO_DATA (scan continues)'
Write-Host ('Backup: ' + $backup)
