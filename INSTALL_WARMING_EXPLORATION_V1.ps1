$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - WARMING EXPLORATION V1 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '43cd3da3df05ec94e45f3c1f77588f41fba82b54'
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
Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-warming-exploration-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('evidence_gate.py','api.py')) {
  $src = Join-Path $app $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_warming_exploration_v1'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$moduleUrl = $root + '/astra_evidence_gate/evidence_gate.py'
$testUrl = $root + '/astra_evidence_gate/selftest_warming_exploration.py'

Write-Host '[1/6] Downloading pinned Evidence Gate module + self-test...'
Invoke-WebRequest -UseBasicParsing -Uri $moduleUrl -OutFile (Join-Path $tmp 'evidence_gate.py')
Invoke-WebRequest -UseBasicParsing -Uri $testUrl -OutFile (Join-Path $tmp 'selftest_warming_exploration.py')
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/6] Syntax + isolated behavior test...'
& python -m py_compile (Join-Path $tmp 'evidence_gate.py') (Join-Path $tmp 'selftest_warming_exploration.py')
if($LASTEXITCODE -ne 0){ throw 'Python syntax failed. Local ASTRA not modified.' }
Push-Location $tmp
try {
  & python '.\selftest_warming_exploration.py'
  if($LASTEXITCODE -ne 0){ throw 'WARMING exploration self-test failed. Local ASTRA not modified.' }
} finally { Pop-Location }
Write-Host '[OK] WARMING exploration self-test passed.' -ForegroundColor Green

Write-Host '[3/6] Installing updated Evidence Gate...'
try {
  Copy-Item (Join-Path $tmp 'evidence_gate.py') (Join-Path $app 'evidence_gate.py') -Force
  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'evidence_gate.py'
    if($LASTEXITCODE -ne 0){ throw 'Final compile failed.' }
  } finally { Pop-Location }
} catch {
  if(Test-Path (Join-Path $backup 'evidence_gate.py')){ Copy-Item (Join-Path $backup 'evidence_gate.py') (Join-Path $app 'evidence_gate.py') -Force }
  Write-Host '[ROLLBACK] Restored previous Evidence Gate.' -ForegroundColor Yellow
  throw
}

Write-Host '[4/6] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[5/6] Waiting for health...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
    if($health.status -eq 'ok' -and $health.evidence_gate -and $health.evidence_gate.exploration){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health check failed.' }
if(-not $health.evidence_gate.exploration){ throw 'Exploration config missing from Evidence Gate health.' }

Write-Host '[6/6] Summary...'
Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - WARMING EXPLORATION V1 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Gate state: ' + $health.evidence_gate.state)
Write-Host ('Evidence n: ' + $health.evidence_gate.evidence_n)
Write-Host ('Exploration enabled: ' + $health.evidence_gate.exploration.enabled)
Write-Host ('Exploration available now: ' + $health.evidence_gate.exploration.available)
Write-Host ('Exploration min EDGE: +' + $health.evidence_gate.exploration.min_edge_pct + '%')
Write-Host ('Exploration cooldown: ' + $health.evidence_gate.exploration.cooldown_sec + ' sec')
Write-Host ('Exploration max open STRICT: ' + $health.evidence_gate.exploration.max_open)
Write-Host ('Current open STRICT: ' + $health.evidence_gate.exploration.open_strict)
Write-Host ''
Write-Host 'Behavior:'
Write-Host ' - WARMING: STRICT 4/4 + EDGE >= +0.10% + JEV APPROVE may open PAPER'
Write-Host ' - max 1 WARMING exploration candidate per scan'
Write-Host ' - max 1 open STRICT exploration position'
Write-Host ' - 10 minute cooldown between exploration passes'
Write-Host ' - HOLD after enough negative evidence remains a hard block'
Write-Host ' - PASS uses the validated threshold normally'
Write-Host ' - Adaptive ML remains downstream and cannot rescue DROP'
Write-Host ' - LIVE routing: NO'
Write-Host ('Backup: ' + $backup)