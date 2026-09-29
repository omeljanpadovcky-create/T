$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - ADAPTIVE ML LEARNER V1 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '7078a7993326f46f28a421183665744e9c7da3da'
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
$backup = Join-Path $app ('backup-before-adaptive-ml-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','adaptive_learner.py','counterfactual_shadow.py','risk_intelligence_shadow.py')) {
  $src = Join-Path $app $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_adaptive_ml_v1'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @{
  'adaptive_learner.py' = $root + '/astra_adaptive_learner/adaptive_learner.py'
  'patch_adaptive_learner.py' = $root + '/astra_adaptive_learner/patch_adaptive_learner.py'
  'selftest_adaptive_learner.py' = $root + '/astra_adaptive_learner/selftest_adaptive_learner.py'
  'counterfactual_shadow.py' = $root + '/astra_counterfactual_shadow/counterfactual_shadow.py'
  'risk_intelligence_shadow.py' = $root + '/astra_risk_intelligence_shadow/risk_intelligence_shadow.py'
}

Write-Host '[1/8] Downloading pinned ML bundle...'
foreach($name in $downloads.Keys){ Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name) }
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/8] Syntax check...'
$pyFiles = @((Join-Path $tmp 'adaptive_learner.py'),(Join-Path $tmp 'patch_adaptive_learner.py'),(Join-Path $tmp 'selftest_adaptive_learner.py'),(Join-Path $tmp 'counterfactual_shadow.py'),(Join-Path $tmp 'risk_intelligence_shadow.py'))
& python -m py_compile @pyFiles
if($LASTEXITCODE -ne 0){ throw 'Downloaded Python syntax invalid. Local ASTRA not modified.' }
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[3/8] Running isolated ML self-test...'
Push-Location $tmp
try {
  & python '.\selftest_adaptive_learner.py'
  if($LASTEXITCODE -ne 0){ throw 'Adaptive ML self-test failed. Local ASTRA not modified.' }
} finally { Pop-Location }
Write-Host '[OK] Adaptive ML self-test passed.' -ForegroundColor Green

Write-Host '[4/8] Installing learner + tracing modules...'
try {
  Copy-Item (Join-Path $tmp 'adaptive_learner.py') (Join-Path $app 'adaptive_learner.py') -Force
  Copy-Item (Join-Path $tmp 'counterfactual_shadow.py') (Join-Path $app 'counterfactual_shadow.py') -Force
  Copy-Item (Join-Path $tmp 'risk_intelligence_shadow.py') (Join-Path $app 'risk_intelligence_shadow.py') -Force
  & python (Join-Path $tmp 'patch_adaptive_learner.py') $app
  if($LASTEXITCODE -ne 0){ throw 'Adaptive ML API patch failed.' }
  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'adaptive_learner.py' 'counterfactual_shadow.py' 'risk_intelligence_shadow.py'
    if($LASTEXITCODE -ne 0){ throw 'Final project compile failed.' }
  } finally { Pop-Location }
} catch {
  if(Test-Path (Join-Path $backup 'api.py')){ Copy-Item (Join-Path $backup 'api.py') (Join-Path $app 'api.py') -Force }
  foreach($f in @('adaptive_learner.py','counterfactual_shadow.py','risk_intelligence_shadow.py')) {
    $old = Join-Path $backup $f; $dst = Join-Path $app $f
    if(Test-Path $old){ Copy-Item $old $dst -Force } elseif(Test-Path $dst){ Remove-Item $dst -Force }
  }
  Write-Host '[ROLLBACK] Restored pre-ML files.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Learner installed.' -ForegroundColor Green

Write-Host '[5/8] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[6/8] Waiting for health...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
    if($health.status -eq 'ok' -and $health.adaptive_learner){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health check failed.' }
if(-not $health.adaptive_learner){ throw 'Adaptive learner missing from /health.' }
Write-Host '[OK] ASTRA health + Adaptive Learner present.' -ForegroundColor Green

Write-Host '[7/8] Reading learner report...'
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
$report = $null
try { $report = Invoke-RestMethod 'http://127.0.0.1:8088/adaptive-learner/report?force=true' -Headers $headers -TimeoutSec 15 } catch {}

Write-Host '[8/8] Summary...'
Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - ADAPTIVE ML LEARNER V1 ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('Learner mode: ' + $health.adaptive_learner.mode)
Write-Host ('Learner state: ' + $health.adaptive_learner.state)
Write-Host ('Source outcomes: ' + $health.adaptive_learner.source_n)
if($health.adaptive_learner.champion){
  Write-Host ('Champion EDGE >= ' + $health.adaptive_learner.champion.edge_threshold_pct + '%')
  Write-Host ('Champion ML p >= ' + $health.adaptive_learner.champion.ml_probability_threshold)
  Write-Host ('Champion holdout n: ' + $health.adaptive_learner.champion.holdout_n)
  Write-Host ('Champion holdout avg NET: ' + $health.adaptive_learner.champion.holdout_avg_net_pct + '%')
  Write-Host ('Champion holdout PF: ' + $health.adaptive_learner.champion.holdout_profit_factor)
} else {
  Write-Host 'Champion: NONE - learner is warming/searching'
}
Write-Host ''
Write-Host 'Safety invariants:'
Write-Host ' - Evidence Gate stays authoritative'
Write-Host ' - learner can ENTER -> DROP only; never DROP -> ENTER'
Write-Host ' - walk-forward older train / newer holdout'
Write-Host ' - no auto code rewriting'
Write-Host ' - no live routing'
Write-Host ' - no extra Bybit market requests'
Write-Host ' - PAPER only'
Write-Host ('Backup: ' + $backup)