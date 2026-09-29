$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '=== MYSHKA / ASTRA - EVIDENCE GATE V1 ===' -ForegroundColor Cyan
$bundleCommit = 'c418a3238d05662117375ee38aecd4f84c9d64b5'
$root = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/' + $bundleCommit

$app = $null
try {
  $raw = docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if ($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir') { $app = $raw[0].Config.Labels.'com.docker.compose.project.working_dir' }
} catch {}
if (-not $app) {
  $fallback = Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if (Test-Path (Join-Path $fallback 'api.py')) { $app = $fallback }
}
if (-not $app -or -not (Test-Path (Join-Path $app 'api.py'))) { throw 'ASTRA project folder not found.' }

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-evidence-gate-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','counterfactual_shadow.py','risk_intelligence_shadow.py','evidence_gate.py')) {
  $src = Join-Path $app $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_evidence_gate_v1'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @{
  'evidence_gate.py' = $root + '/astra_evidence_gate/evidence_gate.py'
  'patch_evidence_gate.py' = $root + '/astra_evidence_gate/patch_evidence_gate.py'
  'selftest_evidence_gate.py' = $root + '/astra_evidence_gate/selftest_evidence_gate.py'
  'counterfactual_shadow.py' = $root + '/astra_counterfactual_shadow/counterfactual_shadow.py'
  'risk_intelligence_shadow.py' = $root + '/astra_risk_intelligence_shadow/risk_intelligence_shadow.py'
}

Write-Host '[1/7] Downloading bundle...'
foreach($name in $downloads.Keys){ Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name) }

Write-Host '[2/7] Syntax check + isolated self-test...'
$pyFiles = @((Join-Path $tmp 'evidence_gate.py'),(Join-Path $tmp 'patch_evidence_gate.py'),(Join-Path $tmp 'selftest_evidence_gate.py'),(Join-Path $tmp 'counterfactual_shadow.py'),(Join-Path $tmp 'risk_intelligence_shadow.py'))
& python -m py_compile @pyFiles
if($LASTEXITCODE -ne 0){ throw 'Downloaded Python syntax invalid.' }
Push-Location $tmp
try {
  & python '.\selftest_evidence_gate.py'
  if($LASTEXITCODE -ne 0){ throw 'Evidence Gate self-test failed. Local ASTRA not modified.' }
} finally { Pop-Location }

Write-Host '[3/7] Installing modules...'
try {
  Copy-Item (Join-Path $tmp 'evidence_gate.py') (Join-Path $app 'evidence_gate.py') -Force
  Copy-Item (Join-Path $tmp 'counterfactual_shadow.py') (Join-Path $app 'counterfactual_shadow.py') -Force
  Copy-Item (Join-Path $tmp 'risk_intelligence_shadow.py') (Join-Path $app 'risk_intelligence_shadow.py') -Force
  & python (Join-Path $tmp 'patch_evidence_gate.py') $app
  if($LASTEXITCODE -ne 0){ throw 'API patch failed.' }
  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'evidence_gate.py' 'counterfactual_shadow.py' 'risk_intelligence_shadow.py'
    if($LASTEXITCODE -ne 0){ throw 'Final project compile failed.' }
  } finally { Pop-Location }
} catch {
  if(Test-Path (Join-Path $backup 'api.py')){ Copy-Item (Join-Path $backup 'api.py') (Join-Path $app 'api.py') -Force }
  foreach($f in @('counterfactual_shadow.py','risk_intelligence_shadow.py','evidence_gate.py')) {
    $old = Join-Path $backup $f; $dst = Join-Path $app $f
    if(Test-Path $old){ Copy-Item $old $dst -Force } elseif(Test-Path $dst){ Remove-Item $dst -Force }
  }
  Write-Host '[ROLLBACK] Restored pre-gate files.' -ForegroundColor Yellow
  throw
}

Write-Host '[4/7] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[5/7] Waiting for health...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try { $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4; if($health.status -eq 'ok'){ break } } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health check failed.' }
if(-not $health.evidence_gate){ throw 'Evidence Gate missing from /health.' }

Write-Host '[6/7] Endpoint check...'
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
try { $gate = Invoke-RestMethod 'http://127.0.0.1:8088/evidence-gate/report' -Headers $headers -TimeoutSec 8 } catch { $gate = $null }

Write-Host '[7/7] Summary...'
Write-Host 'READY - EVIDENCE GATE V1' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Gate mode: ' + $health.evidence_gate.mode)
Write-Host ('Gate state: ' + $health.evidence_gate.state)
Write-Host ('Evidence n: ' + $health.evidence_gate.evidence_n)
if($health.evidence_gate.qualified_threshold_pct -ne $null){
  Write-Host ('Qualified threshold: ' + $health.evidence_gate.qualified_threshold_pct + '%')
} else {
  Write-Host 'Qualified threshold: NONE / WARMING'
}
Write-Host 'Policy: n>=20, avg NET >= +0.03%, PF >= 1.10, recent sample positive'
Write-Host 'Applies only to STRICT 4/4 + EDGE PASS + JEV APPROVE + PAPER ENTER'
Write-Host 'Rejected candidates continue learning through Counterfactual/Risk Intelligence'
Write-Host 'Live trading added: NO'
Write-Host 'Extra market API calls: NO'
Write-Host ('Backup: ' + $backup)