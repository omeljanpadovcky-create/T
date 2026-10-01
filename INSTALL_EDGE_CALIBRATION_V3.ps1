$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - EDGE CALIBRATION V3 ' -ForegroundColor Yellow
Write-Host ' CLUSTERED ISOTONIC - PAPER ONLY ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '5ee6892d5ae104e1900b9ca26080487d168a0837'
$root = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/' + $bundleCommit + '/astra_edge_calibration_v3'
$env:COMPOSE_ANSI = 'never'
$env:BUILDKIT_PROGRESS = 'plain'

$app = $null
try {
  $old = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  $rawText = & docker inspect myshka-astra 2>$null
  $rc = $LASTEXITCODE
  $ErrorActionPreference = $old
  if($rc -eq 0 -and $rawText){
    $raw = $rawText | ConvertFrom-Json
    if ($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir') {
      $app = $raw[0].Config.Labels.'com.docker.compose.project.working_dir'
    }
  }
} catch {}
if (-not $app) {
  $fallback = Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if (Test-Path (Join-Path $fallback 'api.py')) { $app = $fallback }
}
if (-not $app -or -not (Test-Path (Join-Path $app 'api.py'))) { throw 'ASTRA project folder not found.' }
if (-not (Test-Path (Join-Path $app 'edge_calibration_v2.py'))) { throw 'EDGE Calibration V2 is required before V3.' }
if (-not (Test-Path (Join-Path $app 'forward_experiment_lab.py'))) {
  throw 'Forward Experiment Lab is required because V3 learns from its clustered 5m outcomes.'
}
Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-edge-calibration-v3-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','edge_calibration_v2.py','edge_calibration_v3.py')) {
  $src = Join-Path $app $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_edge_calibration_v3'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @{
  'edge_calibration_v3.py' = $root + '/edge_calibration_v3.py'
  'patch_edge_calibration_v3.py' = $root + '/patch_edge_calibration_v3.py'
  'selftest_edge_calibration_v3.py' = $root + '/selftest_edge_calibration_v3.py'
}

Write-Host '[1/8] Downloading pinned V3 bundle...'
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name)
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/8] Syntax check...'
$old = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
foreach($name in $downloads.Keys){
  & python -m py_compile (Join-Path $tmp $name)
  if($LASTEXITCODE -ne 0){
    $ErrorActionPreference = $old
    throw ('Python syntax invalid in ' + $name + '. Local ASTRA not modified.')
  }
}
$ErrorActionPreference = $old
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[3/8] Isolated V3 self-test...'
Push-Location $tmp
try {
  $old = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & python '.\selftest_edge_calibration_v3.py'
  $rc = $LASTEXITCODE
  $ErrorActionPreference = $old
  if($rc -ne 0){ throw 'EDGE Calibration V3 self-test failed.' }
} finally { Pop-Location }
Write-Host '[OK] V3 self-test passed.' -ForegroundColor Green

Write-Host '[4/8] Installing V3 + patching API...'
try {
  Copy-Item (Join-Path $tmp 'edge_calibration_v3.py') (Join-Path $app 'edge_calibration_v3.py') -Force

  $old = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & python (Join-Path $tmp 'patch_edge_calibration_v3.py') $app
  $patchRc = $LASTEXITCODE
  if($patchRc -eq 0){
    Push-Location $app
    try {
      & python -m py_compile 'api.py' 'edge_calibration_v3.py'
      $compileRc = $LASTEXITCODE
    } finally { Pop-Location }
  } else {
    $compileRc = 1
  }
  $ErrorActionPreference = $old

  if($patchRc -ne 0 -or $compileRc -ne 0){ throw 'V3 patch/compile failed.' }
} catch {
  if(Test-Path (Join-Path $backup 'api.py')){
    Copy-Item (Join-Path $backup 'api.py') (Join-Path $app 'api.py') -Force
  }
  if(Test-Path (Join-Path $backup 'edge_calibration_v3.py')){
    Copy-Item (Join-Path $backup 'edge_calibration_v3.py') (Join-Path $app 'edge_calibration_v3.py') -Force
  } elseif(Test-Path (Join-Path $app 'edge_calibration_v3.py')) {
    Remove-Item (Join-Path $app 'edge_calibration_v3.py') -Force
  }
  Write-Host '[ROLLBACK] Pre-V3 source restored.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Source patched and compiled.' -ForegroundColor Green

Write-Host '[5/8] Rebuilding ASTRA...'
Push-Location $app
try {
  $old = $ErrorActionPreference
  $ErrorActionPreference = 'Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc = $LASTEXITCODE
  $ErrorActionPreference = $old
  if($rc -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[6/8] Waiting for ASTRA /health...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
    if($health.status -eq 'ok' -and $health.edge_calibration_v3){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health check failed.' }
if(-not $health.edge_calibration_v3){ throw 'EDGE Calibration V3 missing from /health.' }
if([int]$health.edge_calibration_v3.version -ne 3){ throw 'Wrong calibration version in /health.' }

Write-Host '[7/8] Reading V3 calibration status...'
$v3 = $health.edge_calibration_v3
Write-Host (' State: ' + $v3.state)
Write-Host (' Cluster n: ' + $v3.cluster_n + ' / ' + $v3.min_clusters)
Write-Host (' Horizon: ' + $v3.horizon_sec + ' sec')
Write-Host (' Isotonic blocks: ' + $v3.blocks)
Write-Host (' Raw EDGE<->NET corr: ' + $v3.raw_edge_net_corr)

Write-Host '[8/8] Summary...'
Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - EDGE CALIBRATION V3 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Calibration: V3 - ' + $v3.mode)
Write-Host ('State: ' + $v3.state)
Write-Host ('Independent clusters: ' + $v3.cluster_n + ' / ' + $v3.min_clusters)
Write-Host ('5m horizon: ' + $v3.horizon_sec + ' sec')
Write-Host ('NEUTRAL excluded from active fit: ' + $v3.exclude_neutral_from_fit)
Write-Host ''
Write-Host 'What changed:'
Write-Host ' - manual V2 0.08-0.15 EDGE band is no longer the active calibrator'
Write-Host ' - V3 learns modeled EDGE -> realized 5m NET from clustered forward outcomes'
Write-Host ' - isotonic PAVA prevents higher modeled EDGE from being rewarded when outcomes disagree'
Write-Host ' - STRICT TECH 4/4 only'
Write-Host ' - one pair+side+5m observation per cluster'
Write-Host ' - WARMING until 30 independent clusters'
Write-Host ' - during WARMING, PAPER entries HOLD; SHADOW data collection continues'
Write-Host ''
Write-Host 'Safety invariants:'
Write-Host ' - V3 can only HOLD/DROP an already-passed EDGE candidate'
Write-Host ' - V3 cannot rescue a DROP'
Write-Host ' - V3 cannot create ENTER'
Write-Host ' - Freqtrade LIVE settings unchanged'
Write-Host ' - real-money execution unchanged/disabled'
Write-Host ('Backup: ' + $backup)
