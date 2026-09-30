$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - EVIDENCE PHANTOM COOLDOWN HOTFIX ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = 'd03732f2183a8d96c4a5edec32cb2d4e31e3309a'
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
$backup = Join-Path $app ('backup-before-evidence-phantom-cooldown-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
if(Test-Path (Join-Path $app 'evidence_gate.py')) {
  Copy-Item (Join-Path $app 'evidence_gate.py') (Join-Path $backup 'evidence_gate.py') -Force
}

$tmp = Join-Path $env:TEMP 'myshka_evidence_phantom_cooldown'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/5] Downloading fixed Evidence Gate...'
Invoke-WebRequest -UseBasicParsing -Uri ($root + '/astra_evidence_gate/evidence_gate.py') -OutFile (Join-Path $tmp 'evidence_gate.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root + '/astra_evidence_gate/selftest_warming_exploration.py') -OutFile (Join-Path $tmp 'selftest_warming_exploration.py')

Write-Host '[2/5] Syntax + self-test...'
& python -m py_compile (Join-Path $tmp 'evidence_gate.py') (Join-Path $tmp 'selftest_warming_exploration.py')
if($LASTEXITCODE -ne 0){ throw 'Python syntax failed. Local ASTRA not modified.' }
Push-Location $tmp
try {
  & python '.\selftest_warming_exploration.py'
  if($LASTEXITCODE -ne 0){ throw 'Evidence phantom cooldown self-test failed. Local ASTRA not modified.' }
} finally { Pop-Location }

Write-Host '[3/5] Installing evidence_gate.py...'
Copy-Item (Join-Path $tmp 'evidence_gate.py') (Join-Path $app 'evidence_gate.py') -Force
Push-Location $app
try {
  & python -m py_compile 'api.py' 'evidence_gate.py'
  if($LASTEXITCODE -ne 0){
    if(Test-Path (Join-Path $backup 'evidence_gate.py')) {
      Copy-Item (Join-Path $backup 'evidence_gate.py') (Join-Path $app 'evidence_gate.py') -Force
    }
    throw 'Final compile failed; previous evidence_gate.py restored.'
  }
} finally { Pop-Location }

Write-Host '[4/5] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[5/5] Checking /health...'
$health = $null
for($i=0; $i -lt 40; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health failed after Evidence hotfix.' }

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - EVIDENCE PHANTOM COOLDOWN HOTFIX ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Evidence state: ' + $health.evidence_gate.state)
Write-Host ('Evidence n: ' + $health.evidence_gate.evidence_n)
Write-Host ('Cooldown source: ' + $health.evidence_gate.exploration.cooldown_source)
Write-Host ('Cooldown left: ' + $health.evidence_gate.exploration.cooldown_left_sec + ' sec')
Write-Host ('Open STRICT PAPER: ' + $health.evidence_gate.exploration.open_strict)
Write-Host ''
Write-Host 'Behavior change: SHADOW rows no longer start exploration cooldown'
Write-Host 'Actual STRICT PAPER trades still start the 600s cooldown'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: ' + $backup)
