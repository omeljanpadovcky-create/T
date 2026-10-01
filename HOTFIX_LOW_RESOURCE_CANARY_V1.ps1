$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - LOW RESOURCE CANARY HOTFIX V1 ' -ForegroundColor Yellow
Write-Host ' PERFORMANCE ONLY - TRADING LOGIC UNCHANGED ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='00355381e8b6d0ac719ebe2c61d4befefe35843b'
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
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){
  throw 'ASTRA project folder not found.'
}
if(-not (Test-Path (Join-Path $app '.env.live-armed'))){
  throw '.env.live-armed not found.'
}

Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

Write-Host ''
Write-Host '[0/8] Current Docker load snapshot...' -ForegroundColor Cyan
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' myshka-astra
$ErrorActionPreference=$old

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-low-resource-canary-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null

$targets=@('risk_intelligence_shadow.py','multihorizon_shadow.py','forward_experiment_lab.py','fasttrack_paper_canary.py','.env.live-armed')
foreach($name in $targets){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
if(Test-Path (Join-Path $app 'index.html')){
  Copy-Item (Join-Path $app 'index.html') (Join-Path $backup 'index.html') -Force
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_low_resource_canary_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null
$nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

$files=@{
  'risk_intelligence_shadow.py'=$root+'/astra_risk_intelligence_shadow/risk_intelligence_shadow.py'
  'multihorizon_shadow.py'=$root+'/astra_multihorizon_shadow/multihorizon_shadow.py'
  'forward_experiment_lab.py'=$root+'/astra_forward_experiment_lab/forward_experiment_lab.py'
  'fasttrack_paper_canary.py'=$root+'/astra_fasttrack_canary/fasttrack_paper_canary.py'
  'index.html'=$root+'/index.html'
}

Write-Host '[1/8] Downloading pinned optimized modules...'
foreach($name in $files.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri ($files[$name]+'?x='+$nonce) -Headers @{'User-Agent'='MYSHKA-ASTRA-LowResource';'Cache-Control'='no-cache, no-store, max-age=0';'Pragma'='no-cache'} -OutFile (Join-Path $tmp $name) -TimeoutSec 60
}

Write-Host '[2/8] Verifying performance markers...'
$checks=@{
  'risk_intelligence_shadow.py'=@('RISK_HISTORY_CACHE_SEC','_analytics_snapshot','_cleanup_blackbox','RISK_BLACKBOX_CLEANUP_SEC')
  'multihorizon_shadow.py'=@('status_source','lightweight_counts')
  'forward_experiment_lab.py'=@('_SEEN_RECORD_KEYS','Avoid repeating the same INSERT OR IGNORE')
  'fasttrack_paper_canary.py'=@('ASTRA_FASTTRACK_CANARY_REAPER_SEC','REAPER_SEC')
  'index.html'=@('lastDemoRefresh','300000','600000')
}
foreach($name in $checks.Keys){
  $src=Get-Content (Join-Path $tmp $name) -Raw -Encoding UTF8
  foreach($m in $checks[$name]){
    if($src -notlike ('*'+$m+'*')){throw ('Missing performance marker '+$m+' in '+$name)}
  }
}
Write-Host '[OK] Performance markers verified.' -ForegroundColor Green

Write-Host '[3/8] Python compile...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile (Join-Path $tmp 'risk_intelligence_shadow.py') (Join-Path $tmp 'multihorizon_shadow.py') (Join-Path $tmp 'forward_experiment_lab.py') (Join-Path $tmp 'fasttrack_paper_canary.py')
$compileRc=$LASTEXITCODE
$ErrorActionPreference=$old
if($compileRc -ne 0){throw 'Optimized Python bundle compile failed. Nothing installed.'}
Write-Host '[OK] Python bundle compiles.' -ForegroundColor Green

Write-Host '[4/8] Applying low-resource environment...'
$envPath=Join-Path $app '.env.live-armed'
$envLines=Get-Content $envPath
$envLines=$envLines | Where-Object {
  $_ -notmatch '^NEWS_INTELLIGENCE_ENABLED=' -and
  $_ -notmatch '^NEWS_INTELLIGENCE_POLL_SEC=' -and
  $_ -notmatch '^RISK_HISTORY_CACHE_SEC=' -and
  $_ -notmatch '^RISK_BLACKBOX_CLEANUP_SEC=' -and
  $_ -notmatch '^ASTRA_FASTTRACK_CANARY_REAPER_SEC=' -and
  $_ -notmatch '^RESCUE_MATRIX_REPORT_CACHE_TTL_SEC='
}
$envLines += 'NEWS_INTELLIGENCE_ENABLED=false'
$envLines += 'NEWS_INTELLIGENCE_POLL_SEC=600'
$envLines += 'RISK_HISTORY_CACHE_SEC=60'
$envLines += 'RISK_BLACKBOX_CLEANUP_SEC=300'
$envLines += 'ASTRA_FASTTRACK_CANARY_REAPER_SEC=60'
$envLines += 'RESCUE_MATRIX_REPORT_CACHE_TTL_SEC=120'
$envLines | Set-Content $envPath -Encoding ASCII
Write-Host '[OK] News/Ollama shadow disabled; caches/polling relaxed.' -ForegroundColor Green

Write-Host '[5/8] Installing optimized modules...'
try{
  foreach($name in @('risk_intelligence_shadow.py','multihorizon_shadow.py','forward_experiment_lab.py','fasttrack_paper_canary.py')){
    Copy-Item (Join-Path $tmp $name) (Join-Path $app $name) -Force
  }
  if(Test-Path (Join-Path $app 'index.html')){
    Copy-Item (Join-Path $tmp 'index.html') (Join-Path $app 'index.html') -Force
  }

  Push-Location $app
  try{
    $old=$ErrorActionPreference
    $ErrorActionPreference='Continue'
    & python -m py_compile 'api.py' 'risk_intelligence_shadow.py' 'multihorizon_shadow.py' 'forward_experiment_lab.py' 'fasttrack_paper_canary.py'
    $localRc=$LASTEXITCODE
    $ErrorActionPreference=$old
  }finally{Pop-Location}

  if($localRc -ne 0){throw 'Local compile failed.'}
}catch{
  foreach($name in $targets){
    $b=Join-Path $backup $name
    $dst=Join-Path $app $name
    if(Test-Path $b){Copy-Item $b $dst -Force}
  }
  if(Test-Path (Join-Path $backup 'index.html')){
    Copy-Item (Join-Path $backup 'index.html') (Join-Path $app 'index.html') -Force
  }
  Write-Host '[ROLLBACK] Previous files restored.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Optimized modules installed.' -ForegroundColor Green

Write-Host '[6/8] Rebuilding ASTRA only...'
Push-Location $app
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rebuildRc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rebuildRc -ne 0){throw 'ASTRA rebuild failed.'}
}finally{Pop-Location}

Write-Host '[7/8] Health/latency verification...'
$health=$null
$healthMs=$null
for($i=0;$i -lt 35;$i++){
  Start-Sleep -Seconds 2
  try{
    $sw=[Diagnostics.Stopwatch]::StartNew()
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 6
    $sw.Stop()
    $healthMs=$sw.ElapsedMilliseconds
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed after low-resource hotfix.'}
Write-Host ('[OK] /health: '+$healthMs+' ms') -ForegroundColor Green

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } | ForEach-Object { $_.Substring($_.IndexOf('=')+1) } | Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

$canary=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
if($canary.real_money_execution -ne $false){throw 'Unsafe canary live flag.'}
if($canary.local_dry_run -ne $true){throw 'Canary no longer confirms local dry_run.'}

Write-Host '[8/8] Post-hotfix Docker load snapshot...' -ForegroundColor Cyan
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' myshka-astra
$ErrorActionPreference=$old

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - LOW RESOURCE CANARY V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Health latency: '+$healthMs+' ms')
Write-Host ('Canary reaper: '+$canary.reaper_sec+' sec')
Write-Host 'Risk history DB cache: 60 sec'
Write-Host 'Black Box cleanup: once per 300 sec'
Write-Host 'Forward Lab duplicate INSERT attempts: reduced'
Write-Host 'Multi-Horizon health full report: removed'
Write-Host 'News/Ollama shadow background: OFF'
Write-Host 'Dashboard heavy reports: 5 min instead of 30 sec'
Write-Host 'Dashboard hardening poll: 60 sec instead of 5 sec'
Write-Host 'Dashboard reconcile: 10 min instead of 1 min'
Write-Host ''
Write-Host 'TECH/JEV/Binance logic changed: NO'
Write-Host 'Canary filter changed: NO'
Write-Host 'Freqtrade DRY_RUN changed: NO'
Write-Host 'LIVE armed: NO'
Write-Host ('Backup: '+$backup)
