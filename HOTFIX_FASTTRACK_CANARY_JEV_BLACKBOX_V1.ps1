$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FASTTRACK JEV BLACKBOX HOTFIX V1 ' -ForegroundColor Yellow
Write-Host ' REUSE EXISTING JEV · NO NEW OLLAMA CALLS ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$commit='069830aaafde7df579425f4d575553a9efcd87ec'
$uri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$commit+'/astra_fasttrack_canary/fasttrack_paper_canary.py'
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
  if(Test-Path (Join-Path $fallback 'fasttrack_paper_canary.py')){$app=$fallback}
}
if(-not $app){throw 'ASTRA project folder not found.'}

$dst=Join-Path $app 'fasttrack_paper_canary.py'
if(-not (Test-Path $dst)){throw 'fasttrack_paper_canary.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=$dst+'.before-jev-blackbox-v1-'+$stamp
Copy-Item $dst $backup -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_fasttrack_jev_blackbox_v1.py'
$nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

Write-Host '[1/6] Downloading pinned module...'
Invoke-WebRequest -UseBasicParsing -Uri ($uri+'?x='+$nonce) -Headers @{'User-Agent'='MYSHKA-ASTRA-JEVBlackbox';'Cache-Control'='no-cache, no-store, max-age=0';'Pragma'='no-cache'} -OutFile $tmp -TimeoutSec 60

Write-Host '[2/6] Verifying JEV fallback markers...'
$src=Get-Content $tmp -Raw -Encoding UTF8
foreach($m in @('_blackbox_jev','decision_blackbox','jev_blackbox_hit','jev_direct_hit','last_jev_source','JEV_BLACKBOX_MAX_AGE_SEC')){
  if($src -notlike ('*'+$m+'*')){throw ('Missing marker: '+$m)}
}
if($src -like '*api/generate*' -or $src -like '*api/chat*' -or $src -like '*11434*'){
  throw 'Unexpected direct Ollama HTTP endpoint found in canary module.'
}
Write-Host '[OK] Read-only Black Box JEV fallback verified.' -ForegroundColor Green

Write-Host '[3/6] Compile downloaded module...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile $tmp
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'Downloaded canary module does not compile.'}
Write-Host '[OK] Syntax valid.' -ForegroundColor Green

Write-Host '[4/6] Installing module...'
Copy-Item $tmp $dst -Force
Push-Location $app
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python -m py_compile 'fasttrack_paper_canary.py' 'api.py'
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){
    Copy-Item $backup $dst -Force
    throw 'Local compile failed; previous module restored.'
  }
}finally{Pop-Location}
Write-Host '[OK] Module installed.' -ForegroundColor Green

Write-Host '[5/6] Rebuilding ASTRA only...'
Push-Location $app
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){
    Copy-Item $backup $dst -Force
    throw 'ASTRA rebuild failed; previous module restored.'
  }
}finally{Pop-Location}

Write-Host '[6/6] Verifying health and live funnel...'
$health=$null
for($i=0;$i -lt 35;$i++){
  Start-Sleep -Seconds 2
  try{
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 6
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed.'}

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } | ForEach-Object { $_.Substring($_.IndexOf('=')+1) } | Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

$st=$null
for($i=0;$i -lt 12;$i++){
  Start-Sleep -Seconds 5
  $st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
  $f=$st.live_funnel
  Write-Host ('scan='+$f.scan_calls+' tech3='+$f.tech3+' jev='+$f.jev_approve+' direct='+$f.jev_direct_hit+' blackbox='+$f.jev_blackbox_hit+' wait='+$f.jev_wait+' agree='+$f.binance_agree+' triple='+$f.triple_eligible+' sent='+$f.sent+' last='+$f.last_stage+' jevsrc='+$f.last_jev_source)
  if([int]$f.scan_calls -ge 3){break}
}

if($st.real_money_execution -ne $false){throw 'Unsafe real-money canary flag.'}
if($st.local_dry_run -ne $true){throw 'Canary no longer confirms DRY_RUN.'}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - FASTTRACK JEV BLACKBOX V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
$st.live_funnel | ConvertTo-Json -Depth 6
Write-Host ''
Write-Host ('JEV Black Box max age: '+$st.jev_blackbox_max_age_sec+' sec')
Write-Host 'New Ollama/JEV calls: NO'
Write-Host 'Canary filter changed: NO'
Write-Host 'Freqtrade DRY_RUN changed: NO'
Write-Host 'LIVE armed: NO'
Write-Host ('Backup: '+$backup)
