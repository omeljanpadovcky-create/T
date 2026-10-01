$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - ADAPTIVE LEARNER STATUS HOTFIX ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit='f4da48da070687890c36f63890c91243f7e82045'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$bundleCommit
$env:COMPOSE_ANSI='never'
$env:BUILDKIT_PROGRESS='plain'

$app=$null
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  $rawText=& docker inspect myshka-astra 2>$null
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -eq 0 -and $rawText){
    $raw=$rawText | ConvertFrom-Json
    if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
      $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
    }
  }
}catch{}

if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback 'api.py')){$app=$fallback}
}

if(-not $app -or -not (Test-Path (Join-Path $app 'adaptive_learner.py'))){
  throw 'ASTRA project/adaptive_learner.py not found.'
}

Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-adaptive-learner-status-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item (Join-Path $app 'adaptive_learner.py') (Join-Path $backup 'adaptive_learner.py') -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_adaptive_learner_status_hotfix'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/6] Downloading fixed learner...'
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_adaptive_learner/adaptive_learner.py') -OutFile (Join-Path $tmp 'adaptive_learner.py')

Write-Host '[2/6] Syntax check...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile (Join-Path $tmp 'adaptive_learner.py')
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'Downloaded adaptive_learner.py syntax invalid.'}
Write-Host '[OK] Syntax valid.' -ForegroundColor Green

Write-Host '[3/6] Installing fixed learner...'
Copy-Item (Join-Path $tmp 'adaptive_learner.py') (Join-Path $app 'adaptive_learner.py') -Force
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
Push-Location $app
try{
  & python -m py_compile 'adaptive_learner.py' 'api.py'
  $rc=$LASTEXITCODE
}finally{Pop-Location}
$ErrorActionPreference=$old
if($rc -ne 0){
  Copy-Item (Join-Path $backup 'adaptive_learner.py') (Join-Path $app 'adaptive_learner.py') -Force
  throw 'Local compile failed; previous learner restored.'
}
Write-Host '[OK] Learner patched.' -ForegroundColor Green

Write-Host '[4/6] Rebuilding ASTRA...'
Push-Location $app
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){throw 'ASTRA rebuild failed.'}
}finally{Pop-Location}

Write-Host '[5/6] Waiting for fast /health...'
$health=$null
$healthMs=$null
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 2
  try{
    $sw=[Diagnostics.Stopwatch]::StartNew()
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    $sw.Stop()
    $healthMs=$sw.ElapsedMilliseconds
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){
  Write-Host '[FAIL] /health still not responsive.' -ForegroundColor Red
  docker logs --tail 50 myshka-astra
  throw 'ASTRA /health failed after learner hotfix.'
}
Write-Host ('[OK] /health: '+$healthMs+' ms') -ForegroundColor Green

Write-Host '[6/6] Checking /control/status...'
$sw=[Diagnostics.Stopwatch]::StartNew()
$ctl=Invoke-RestMethod 'http://127.0.0.1:8088/control/status' -TimeoutSec 5
$sw.Stop()
Write-Host ('[OK] /control/status: '+$sw.ElapsedMilliseconds+' ms') -ForegroundColor Green

$learner=$health.adaptive_learner
Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - ADAPTIVE LEARNER STATUS HOTFIX ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: '+$health.status)
Write-Host ('Learner state: '+$learner.state)
Write-Host ('Learner source n: '+$learner.source_n)
Write-Host ('Learner status source: '+$learner.status_source)
Write-Host ('Health latency: '+$healthMs+' ms')
Write-Host ''
Write-Host 'What changed:'
Write-Host ' - /health no longer triggers full learner rebuild'
Write-Host ' - learner status uses memory cache or latest snapshot only'
Write-Host ' - learner report checks cache BEFORE scanning risk DB'
Write-Host ' - trading model / thresholds / decisions unchanged'
Write-Host ' - DRY_RUN / LIVE routing unchanged'
Write-Host ('Backup: '+$backup)
