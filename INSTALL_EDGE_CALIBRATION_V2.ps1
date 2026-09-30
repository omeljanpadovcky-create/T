$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - EDGE CALIBRATION V2 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '9ae7ce762f90f444c3441e2bda4d424294638f6d'
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
if (-not $app -or -not (Test-Path (Join-Path $app 'api.py'))) { throw 'ASTRA project folder not found.' }
if (-not (Test-Path (Join-Path $app 'jev.py'))) { throw 'jev.py not found.' }
Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-edge-calibration-v2-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','jev.py','evidence_gate.py','edge_calibration_v2.py','multihorizon_shadow.py')) {
  $src = Join-Path $app $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_edge_calibration_v2'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @{
  'edge_calibration_v2.py' = $root + '/astra_edge_calibration_v2/edge_calibration_v2.py'
  'patch_edge_calibration_v2.py' = $root + '/astra_edge_calibration_v2/patch_edge_calibration_v2.py'
  'selftest_edge_calibration_v2.py' = $root + '/astra_edge_calibration_v2/selftest_edge_calibration_v2.py'
  'multihorizon_shadow.py' = $root + '/astra_multihorizon_shadow/multihorizon_shadow.py'
  'selftest_multihorizon_shadow.py' = $root + '/astra_multihorizon_shadow/selftest_multihorizon_shadow.py'
  'evidence_gate.py' = $root + '/astra_evidence_gate/evidence_gate.py'
  'selftest_evidence_gate.py' = $root + '/astra_evidence_gate/selftest_evidence_gate.py'
  'selftest_warming_exploration.py' = $root + '/astra_evidence_gate/selftest_warming_exploration.py'
}

Write-Host '[1/8] Downloading pinned bundle...'
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name)
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/8] Syntax check...'
foreach($name in $downloads.Keys){
  $p = Join-Path $tmp $name
  Write-Host ('  compile: ' + $name)
  & python -m py_compile $p
  if($LASTEXITCODE -ne 0){ throw ('Downloaded Python syntax invalid in ' + $name + '. Local ASTRA not modified.') }
}
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[3/8] Running isolated self-tests...'
Push-Location $tmp
try {
  & python '.\selftest_edge_calibration_v2.py'
  if($LASTEXITCODE -ne 0){ throw 'EDGE Calibration V2 self-test failed.' }

  & python '.\selftest_multihorizon_shadow.py'
  if($LASTEXITCODE -ne 0){ throw 'Multi-Horizon self-test failed.' }

  & python '.\selftest_warming_exploration.py'
  if($LASTEXITCODE -ne 0){ throw 'WARMING band self-test failed.' }

  & python '.\selftest_evidence_gate.py'
  if($LASTEXITCODE -ne 0){ throw 'Evidence Gate self-test failed.' }
} finally { Pop-Location }
Write-Host '[OK] All isolated self-tests passed.' -ForegroundColor Green

Write-Host '[4/8] Installing calibrated modules...'
try {
  Copy-Item (Join-Path $tmp 'edge_calibration_v2.py') (Join-Path $app 'edge_calibration_v2.py') -Force
  Copy-Item (Join-Path $tmp 'multihorizon_shadow.py') (Join-Path $app 'multihorizon_shadow.py') -Force
  Copy-Item (Join-Path $tmp 'evidence_gate.py') (Join-Path $app 'evidence_gate.py') -Force

  & python (Join-Path $tmp 'patch_edge_calibration_v2.py') $app
  if($LASTEXITCODE -ne 0){ throw 'API/JEV patch failed.' }

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'jev.py' 'evidence_gate.py' 'edge_calibration_v2.py' 'multihorizon_shadow.py'
    if($LASTEXITCODE -ne 0){ throw 'Final project compile failed.' }
  } finally { Pop-Location }
} catch {
  foreach($f in @('api.py','jev.py','evidence_gate.py','edge_calibration_v2.py','multihorizon_shadow.py')) {
    $old = Join-Path $backup $f
    $dst = Join-Path $app $f
    if(Test-Path $old){ Copy-Item $old $dst -Force }
    elseif((Test-Path $dst) -and ($f -in @('edge_calibration_v2.py','multihorizon_shadow.py'))){ Remove-Item $dst -Force }
  }
  Write-Host '[ROLLBACK] Restored pre-V2 files.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Source patched and compiled.' -ForegroundColor Green

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
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
    if($health.status -eq 'ok' -and $health.edge_calibration_v2 -and $health.multihorizon_shadow){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health check failed.' }
if(-not $health.edge_calibration_v2){ throw 'EDGE Calibration V2 missing from /health.' }
if(-not $health.multihorizon_shadow){ throw 'Multi-Horizon SHADOW missing from /health.' }

Write-Host '[7/8] Checking calibrated Evidence Gate...'
$gate = $health.evidence_gate
if(-not $gate){ throw 'Evidence Gate missing from /health.' }
if([double]$gate.exploration.min_edge_pct -ne 0.08){ throw 'Evidence exploration min EDGE is not 0.08.' }
if([double]$gate.exploration.max_edge_pct -ne 0.15){ throw 'Evidence exploration max EDGE is not 0.15.' }

Write-Host '[8/8] Summary...'
Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - EDGE CALIBRATION V2 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Calibration mode: ' + $health.edge_calibration_v2.mode)
Write-Host ('EDGE band: +' + $health.edge_calibration_v2.min_edge_pct + '% .. +' + $health.edge_calibration_v2.max_edge_pct + '%')
Write-Host ('Bootstrap overextension 5m: ' + $health.edge_calibration_v2.bootstrap_max_directional_5m_pct + '%')
Write-Host ('Bootstrap overextension 15m: ' + $health.edge_calibration_v2.bootstrap_max_directional_15m_pct + '%')
Write-Host ('Evidence state: ' + $gate.state)
Write-Host ('Evidence n: ' + $gate.evidence_n)
Write-Host ('Exploration band: +' + $gate.exploration.min_edge_pct + '% .. +' + $gate.exploration.max_edge_pct + '%')
Write-Host ('Multi-Horizon: ' + ($health.multihorizon_shadow.horizons_sec -join ',') + ' sec')
Write-Host ''
Write-Host 'Safety invariants:'
Write-Host ' - Calibration can only reject; never creates/rescues ENTER'
Write-Host ' - Evidence Gate remains active'
Write-Host ' - Adaptive ML remains downstream'
Write-Host ' - Ollama *_pct units explicitly fixed'
Write-Host ' - 5m/10m/15m validation is SHADOW only'
Write-Host ' - no extra market API calls'
Write-Host ' - LIVE routing added: NO'
Write-Host ('Backup: ' + $backup)
