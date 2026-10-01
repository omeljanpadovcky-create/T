$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - EDGE V3 NONBLOCKING HOTFIX ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit='5ee6892d5ae104e1900b9ca26080487d168a0837'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$bundleCommit+'/astra_edge_calibration_v3'
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
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){throw 'ASTRA project folder not found.'}
Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-edge-v3-nonblocking-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('edge_calibration_v3.py','api.py')){
  $src=Join-Path $app $f
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $f) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_edge_v3_nonblocking_hotfix'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/6] Downloading fixed V3 module...'
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/edge_calibration_v3.py') -OutFile (Join-Path $tmp 'edge_calibration_v3.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/selftest_edge_calibration_v3.py') -OutFile (Join-Path $tmp 'selftest_edge_calibration_v3.py')

Write-Host '[2/6] Syntax + self-test...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile (Join-Path $tmp 'edge_calibration_v3.py') (Join-Path $tmp 'selftest_edge_calibration_v3.py')
$rc1=$LASTEXITCODE
if($rc1 -eq 0){
  Push-Location $tmp
  try{
    & python '.\selftest_edge_calibration_v3.py'
    $rc2=$LASTEXITCODE
  }finally{Pop-Location}
}else{$rc2=1}
$ErrorActionPreference=$old
if($rc1 -ne 0 -or $rc2 -ne 0){throw 'V3 fixed module self-test failed.'}
Write-Host '[OK] Fixed V3 module validated.' -ForegroundColor Green

Write-Host '[3/6] Installing fixed V3 module...'
Copy-Item (Join-Path $tmp 'edge_calibration_v3.py') (Join-Path $app 'edge_calibration_v3.py') -Force
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
Push-Location $app
try{
  & python -m py_compile 'api.py' 'edge_calibration_v3.py'
  $rc=$LASTEXITCODE
}finally{Pop-Location}
$ErrorActionPreference=$old
if($rc -ne 0){
  Copy-Item (Join-Path $backup 'edge_calibration_v3.py') (Join-Path $app 'edge_calibration_v3.py') -Force
  throw 'Compile failed; previous V3 restored.'
}
Write-Host '[OK] Fixed V3 installed.' -ForegroundColor Green

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
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 2
  try{
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){
  Write-Host '[FAIL] /health still not responsive.' -ForegroundColor Red
  docker logs --tail 50 myshka-astra
  throw 'ASTRA /health failed after nonblocking hotfix.'
}
Write-Host '[OK] ASTRA health responds.' -ForegroundColor Green

Write-Host '[6/6] V3 quick status...'
$v3=$health.edge_calibration_v3
if($v3){
  Write-Host (' State: '+$v3.state)
  Write-Host (' Cluster n: '+$v3.cluster_n+' / '+$v3.min_clusters)
  Write-Host (' Refreshing: '+$v3.refreshing)
  Write-Host (' Cache age sec: '+$v3.cache_age_sec)
}else{
  Write-Host '[WARN] V3 status not yet present in /health.'
}

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - EDGE V3 NONBLOCKING HOTFIX ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host 'HTTP health/report no longer wait for full SQLite recalculation.'
Write-Host 'Calibration refresh runs in background.'
Write-Host 'Trading logic changed: NO'
Write-Host 'LIVE routing changed: NO'
Write-Host ('Backup: '+$backup)
