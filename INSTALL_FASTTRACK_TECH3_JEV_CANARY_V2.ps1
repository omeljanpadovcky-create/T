$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - TECH3 -> BINANCE -> JEV CANARY V2 ' -ForegroundColor Yellow
Write-Host ' PRODUCTION LOGIC UNCHANGED ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$commit='31e2eab0988cc7483d9e57a0a7c77342b782ce28'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$commit
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
if(-not $app){throw 'ASTRA project folder not found.'}

$api=Join-Path $app 'api.py'
$canary=Join-Path $app 'fasttrack_paper_canary.py'
if(-not (Test-Path $api)){throw 'api.py not found.'}
if(-not (Test-Path $canary)){throw 'fasttrack_paper_canary.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-tech3-jev-canary-v2-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
Copy-Item $api (Join-Path $backup 'api.py') -Force
Copy-Item $canary (Join-Path $backup 'fasttrack_paper_canary.py') -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_tech3_jev_canary_v2'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$uCanary=$root+'/astra_fasttrack_canary/fasttrack_paper_canary.py?x='+$nonce
$uPatcher=$root+'/astra_fasttrack_canary/patch_fasttrack_shadow_ctx_v1.py?x='+$nonce

Write-Host '[1/8] Downloading pinned V2 files...'
Invoke-WebRequest -UseBasicParsing -Uri $uCanary -Headers @{'Cache-Control'='no-cache, no-store, max-age=0';'Pragma'='no-cache'} -OutFile (Join-Path $tmp 'fasttrack_paper_canary.py') -TimeoutSec 60
Invoke-WebRequest -UseBasicParsing -Uri $uPatcher -Headers @{'Cache-Control'='no-cache, no-store, max-age=0';'Pragma'='no-cache'} -OutFile (Join-Path $tmp 'patch_fasttrack_shadow_ctx_v1.py') -TimeoutSec 60

Write-Host '[2/8] Verifying markers...'
$csrc=Get-Content (Join-Path $tmp 'fasttrack_paper_canary.py') -Raw -Encoding UTF8
$psrc=Get-Content (Join-Path $tmp 'patch_fasttrack_shadow_ctx_v1.py') -Raw -Encoding UTF8
foreach($m in @('_shadow_jev','jev_shadow_hit','binance_checked','shadow_real_jev','fasttrack_shadow_ctx')){
  if($csrc -notlike ('*'+$m+'*')){throw ('Missing canary marker: '+$m)}
}
foreach($m in @('MYSHKA_FASTTRACK_SHADOW_CTX_V1','fasttrack_shadow_ctx')){
  if($psrc -notlike ('*'+$m+'*')){throw ('Missing patcher marker: '+$m)}
}
Write-Host '[OK] V2 markers verified.' -ForegroundColor Green

Write-Host '[3/8] Compile downloaded files...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile (Join-Path $tmp 'fasttrack_paper_canary.py') (Join-Path $tmp 'patch_fasttrack_shadow_ctx_v1.py')
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'Downloaded V2 files do not compile.'}
Write-Host '[OK] Downloaded files compile.' -ForegroundColor Green

Write-Host '[4/8] Dry-run API patch on a copy...'
$dry=Join-Path $tmp 'dryrun'
New-Item -ItemType Directory -Path $dry -Force | Out-Null
Copy-Item $api (Join-Path $dry 'api.py') -Force
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python (Join-Path $tmp 'patch_fasttrack_shadow_ctx_v1.py') $dry
$patchRc=$LASTEXITCODE
if($patchRc -eq 0){
  & python -m py_compile (Join-Path $dry 'api.py')
  $compileDryRc=$LASTEXITCODE
}else{
  $compileDryRc=1
}
$ErrorActionPreference=$old
if($patchRc -ne 0 -or $compileDryRc -ne 0){
  throw 'Dry-run API patch failed. Local ASTRA unchanged.'
}
$drySrc=Get-Content (Join-Path $dry 'api.py') -Raw -Encoding UTF8
if($drySrc -notlike '*MYSHKA_FASTTRACK_SHADOW_CTX_V1*'){throw 'Dry-run marker missing.'}
Write-Host '[OK] API patch works on copy.' -ForegroundColor Green

Write-Host '[5/8] Installing V2 canary + shadow context patch...'
try{
  Copy-Item (Join-Path $tmp 'fasttrack_paper_canary.py') $canary -Force

  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python (Join-Path $tmp 'patch_fasttrack_shadow_ctx_v1.py') $app
  $patchLiveRc=$LASTEXITCODE
  if($patchLiveRc -eq 0){
    Push-Location $app
    try{
      & python -m py_compile 'api.py' 'fasttrack_paper_canary.py'
      $compileLiveRc=$LASTEXITCODE
    }finally{Pop-Location}
  }else{
    $compileLiveRc=1
  }
  $ErrorActionPreference=$old

  if($patchLiveRc -ne 0 -or $compileLiveRc -ne 0){throw 'Local V2 install compile failed.'}
}catch{
  Copy-Item (Join-Path $backup 'api.py') $api -Force
  Copy-Item (Join-Path $backup 'fasttrack_paper_canary.py') $canary -Force
  Write-Host '[ROLLBACK] Previous api.py and canary restored.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Local files installed and compile.' -ForegroundColor Green

Write-Host '[6/8] Rebuilding ASTRA only...'
Push-Location $app
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){
    Copy-Item (Join-Path $backup 'api.py') $api -Force
    Copy-Item (Join-Path $backup 'fasttrack_paper_canary.py') $canary -Force
    throw 'ASTRA rebuild failed; previous files restored.'
  }
}finally{Pop-Location}

Write-Host '[7/8] Health + DRY_RUN safety check...'
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
$st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
if($st.real_money_execution -ne $false){throw 'Unsafe real_money_execution flag.'}
if($st.local_dry_run -ne $true){throw 'Freqtrade DRY_RUN confirmation failed.'}

Write-Host '[8/8] Watching the new funnel...' -ForegroundColor Cyan
for($i=0;$i -lt 16;$i++){
  Start-Sleep -Seconds 5
  $st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
  $f=$st.live_funnel
  Write-Host ('scan='+$f.scan_calls+' tech3='+$f.tech3+' bxChecked='+$f.binance_checked+' agree='+$f.binance_agree+' noAgree='+$f.binance_no_agree+' jev='+$f.jev_approve+' shadowJev='+$f.jev_shadow_hit+' edgeReject='+$f.jev_shadow_edge_reject+' ai='+$f.jev_shadow_ai_attempted+' triple='+$f.triple_eligible+' sent='+$f.sent+' last='+$f.last_stage+' jevsrc='+$f.last_jev_source)
  if([int]$f.scan_calls -ge 3){break}
}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - TECH3 -> BINANCE -> JEV CANARY V2 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
$st.live_funnel | ConvertTo-Json -Depth 6
Write-Host ''
Write-Host 'Production signal rules changed: NO'
Write-Host 'Production JEV/EDGE/Guard decisions changed: NO'
Write-Host 'Shadow JEV order: TECH3 -> BINANCE AGREE -> EDGE -> JEV'
Write-Host 'Repeated JEV per 5m pair+side cluster: CACHED'
Write-Host 'Freqtrade DRY_RUN changed: NO'
Write-Host 'LIVE armed: NO'
Write-Host ('Backup: '+$backup)
