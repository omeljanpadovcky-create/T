$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - BYBIT 5M EDGE COLD-START V1 ' -ForegroundColor Yellow
Write-Host ' POOLED 5M HISTORY FIRST - DRY_RUN ONLY ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$patchCommit='fd0796b4028ed54621092f24f6547c9d94d28145'
$patchUri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$patchCommit+'/astra_edge_bybit_5m_bootstrap/patch_edge_bybit_5m_bootstrap.py'
$env:COMPOSE_ANSI='never'
$env:BUILDKIT_PROGRESS='plain'

function Get-AppFolder {
  try {
    $rawText=& docker inspect myshka-astra 2>$null
    if($LASTEXITCODE -eq 0 -and $rawText){
      $raw=$rawText | ConvertFrom-Json
      $wd=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
      if($wd){ return $wd }
    }
  } catch {}
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback 'edge.py')){ return $fallback }
  return $null
}

function Get-BridgeHeaders {
  $token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } | ForEach-Object { $_.Substring($_.IndexOf('=')+1) } | Select-Object -First 1)
  if(-not $token){ throw 'MYSHKA_BRIDGE_TOKEN not found.' }
  return @{'X-MYSHKA-TOKEN'=$token}
}

$app=Get-AppFolder
if(-not $app){ throw 'ASTRA project folder not found.' }
$edge=Join-Path $app 'edge.py'
if(-not (Test-Path $edge)){ throw ('edge.py not found: '+$edge) }

Write-Host ('Project: '+$app)
Write-Host '[1/7] Preflight: DRY_RUN safety...'

$headers=Get-BridgeHeaders
$st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
if($st.real_money_execution -ne $false){ throw 'STOP: real_money_execution is not false.' }
if($st.local_dry_run -ne $true){ throw 'STOP: Freqtrade DRY_RUN is not confirmed.' }
Write-Host '[OK] DRY_RUN confirmed before patch.' -ForegroundColor Green

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=$edge+'.before-bybit-5m-bootstrap-v1-'+$stamp
Copy-Item $edge $backup -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

Write-Host '[2/7] Downloading pinned patcher...'
$tmp=Join-Path $env:TEMP 'patch_edge_bybit_5m_bootstrap.py'
$nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
Invoke-WebRequest -UseBasicParsing -Uri ($patchUri+'?x='+$nonce) -Headers @{'User-Agent'='MYSHKA-ASTRA-Bybit5MEdgeV1';'Cache-Control'='no-cache, no-store, max-age=0';'Pragma'='no-cache'} -OutFile $tmp -TimeoutSec 60

Write-Host '[3/7] Patching edge.py...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python $tmp $edge
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){
  Copy-Item $backup $edge -Force
  throw 'edge.py patch failed; backup restored.'
}

$src=Get-Content $edge -Raw -Encoding UTF8
if($src -notmatch '"pooled_5m"' -or $src -notmatch 'Cold-start V1'){
  Copy-Item $backup $edge -Force
  throw 'Patch markers missing; backup restored.'
}

Write-Host '[4/7] Syntax check...'
Push-Location $app
try {
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python -m py_compile 'edge.py' 'api.py' 'fasttrack_paper_canary.py'
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){
    Copy-Item $backup $edge -Force
    throw 'Compile failed; backup restored.'
  }

  Write-Host '[5/7] Rebuilding ASTRA only...'
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){
    Copy-Item $backup $edge -Force
    throw 'ASTRA rebuild failed. edge.py backup restored locally.'
  }
} finally { Pop-Location }

Write-Host '[6/7] Health + post-patch DRY_RUN check...'
$health=$null
for($i=0;$i -lt 35;$i++){
  Start-Sleep -Seconds 2
  try {
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 6
    if($health.status -eq 'ok'){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health failed after rebuild.' }

$headers=Get-BridgeHeaders
$st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
if($st.real_money_execution -ne $false){ throw 'STOP: unsafe real_money_execution after patch.' }
if($st.local_dry_run -ne $true){ throw 'STOP: Freqtrade DRY_RUN lost after patch.' }
Write-Host '[OK] DRY_RUN still ON. Real-money execution OFF.' -ForegroundColor Green

Write-Host '[7/7] Checking 5m pooled Bybit learner support...'
$py='import numpy as np; from myshka_astra.stats_store import get_pooled_samples; from myshka_astra.config import CONFIG; x=list(get_pooled_samples(300)); print("pooled_5m_n="+str(len(x))); print("min_soft="+str(CONFIG.MIN_SAMPLES_SOFT)); print("pooled_5m_q="+(str(float(np.quantile(x, CONFIG.EXPECTED_MOVE_QUANTILE))) if x else "n/a"))'
try {
  & docker exec myshka-astra python -c $py
} catch {
  Write-Host ('[WARN] Could not print pooled 5m support: '+$_.Exception.Message) -ForegroundColor Yellow
}

Write-Host ''
Write-Host 'Installed rule:' -ForegroundColor Cyan
Write-Host ' bucket FULL   -> bucket quantile'
Write-Host ' bucket WARM   -> bucket shrunk toward pooled 5m'
Write-Host ' bucket COLD   -> pooled 5m quantile when pooled n >= MIN_SAMPLES_SOFT'
Write-Host ' both COLD     -> legacy ATR x 0.5 fallback'
Write-Host ''
Write-Host 'UNCHANGED:' -ForegroundColor Cyan
Write-Host ' - EDGE cost model'
Write-Host ' - net_edge > 0 pass rule'
Write-Host ' - JEV rules'
Write-Host ' - Bybit execution mode'
Write-Host ' - Freqtrade DRY_RUN'
Write-Host ' - real-money execution remains OFF'
Write-Host ''
Write-Host ('Backup: '+$backup)
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' BYBIT 5M EDGE COLD-START V1 READY ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
