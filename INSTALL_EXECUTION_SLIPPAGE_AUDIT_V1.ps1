$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - EXECUTION SLIPPAGE AUDIT V1 ' -ForegroundColor Yellow
Write-Host ' FREQTRADE DRY_RUN + FUTURE LIVE TELEMETRY ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='d661610e84271edcbdacc013422bda230b1b9ec3'
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
if(-not (Test-Path (Join-Path $app 'freqtrade_dryrun_bridge.py'))){
  throw 'freqtrade_dryrun_bridge.py not found.'
}

Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-slippage-audit-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null

foreach($name in @('api.py','freqtrade_dryrun_bridge.py','freqtrade_live_bridge.py','execution_slippage_audit.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_execution_slippage_audit_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads=@{
  'execution_slippage_audit.py'=$root+'/astra_execution_audit/execution_slippage_audit.py'
  'patch_execution_slippage_audit.py'=$root+'/astra_execution_audit/patch_execution_slippage_audit.py'
  'selftest_execution_slippage_audit.py'=$root+'/astra_execution_audit/selftest_execution_slippage_audit.py'
  'freqtrade_dryrun_bridge.py'=$root+'/astra_freqtrade_dryrun_bridge/freqtrade_dryrun_bridge.py'
  'freqtrade_live_bridge.py'=$root+'/astra_freqtrade_live_bridge/freqtrade_live_bridge.py'
}

Write-Host '[1/8] Downloading pinned bundle...'
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name) -TimeoutSec 60
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/8] Syntax check...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
foreach($name in $downloads.Keys){
  & python -m py_compile (Join-Path $tmp $name)
  if($LASTEXITCODE -ne 0){
    $ErrorActionPreference=$old
    throw ('Syntax error in '+$name)
  }
}
$ErrorActionPreference=$old
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[3/8] Isolated slippage self-test...'
Push-Location $tmp
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python '.\selftest_execution_slippage_audit.py'
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){throw 'Execution slippage audit self-test failed.'}
}finally{Pop-Location}
Write-Host '[OK] Slippage math self-test passed.' -ForegroundColor Green

Write-Host '[4/8] Installing modules + API endpoints...'
try{
  Copy-Item (Join-Path $tmp 'execution_slippage_audit.py') (Join-Path $app 'execution_slippage_audit.py') -Force
  Copy-Item (Join-Path $tmp 'freqtrade_dryrun_bridge.py') (Join-Path $app 'freqtrade_dryrun_bridge.py') -Force

  if(Test-Path (Join-Path $app 'freqtrade_live_bridge.py')){
    Copy-Item (Join-Path $tmp 'freqtrade_live_bridge.py') (Join-Path $app 'freqtrade_live_bridge.py') -Force
  }

  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python (Join-Path $tmp 'patch_execution_slippage_audit.py') $app
  $patchRc=$LASTEXITCODE
  if($patchRc -eq 0){
    Push-Location $app
    try{
      $compile=@('api.py','execution_slippage_audit.py','freqtrade_dryrun_bridge.py')
      if(Test-Path '.\freqtrade_live_bridge.py'){$compile+='freqtrade_live_bridge.py'}
      & python -m py_compile @compile
      $compileRc=$LASTEXITCODE
    }finally{Pop-Location}
  }else{$compileRc=1}
  $ErrorActionPreference=$old

  if($patchRc -ne 0 -or $compileRc -ne 0){throw 'Patch/final compile failed.'}
}catch{
  foreach($name in @('api.py','freqtrade_dryrun_bridge.py','freqtrade_live_bridge.py','execution_slippage_audit.py')){
    $b=Join-Path $backup $name
    $dst=Join-Path $app $name
    if(Test-Path $b){Copy-Item $b $dst -Force}
    elseif($name -eq 'execution_slippage_audit.py' -and (Test-Path $dst)){Remove-Item $dst -Force}
  }
  Write-Host '[ROLLBACK] Previous modules restored.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Audit installed.' -ForegroundColor Green

Write-Host '[5/8] Rebuilding ASTRA only...'
Push-Location $app
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){throw 'ASTRA rebuild failed.'}
}finally{Pop-Location}

Write-Host '[6/8] Waiting for ASTRA health...'
$health=$null
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 2
  try{
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok' -and $health.execution_slippage_audit){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA /health failed.'}
if(-not $health.execution_slippage_audit){throw 'Slippage audit missing from /health.'}
Write-Host '[OK] ASTRA health + slippage audit ready.' -ForegroundColor Green

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  ForEach-Object { $_.Substring($_.IndexOf('=')+1) } |
  Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

Write-Host '[7/8] Checking audit endpoint...'
$st=Invoke-RestMethod 'http://127.0.0.1:8088/slippage-audit/status' -Headers $headers -TimeoutSec 10
if($st.mode -ne 'FREQTRADE_EXECUTION_SLIPPAGE_AUDIT_V1'){throw ('Unexpected audit mode: '+$st.mode)}
Write-Host ('[OK] Mode: '+$st.mode) -ForegroundColor Green
Write-Host ('[OK] Telegram configured: '+$st.telegram_configured) -ForegroundColor Green
Write-Host ('[OK] Critical alert: '+$st.alert_bps+' bps') -ForegroundColor Green

Write-Host '[8/8] Safety check...'
$dry=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-dryrun/status' -Headers $headers -TimeoutSec 10
Write-Host ('Freqtrade bridge local dry-run: '+$dry.local_dry_run)
Write-Host ('Real-money execution flag: '+$dry.real_money_execution)
if($dry.real_money_execution -ne $false){throw 'Unsafe dry-run bridge flag.'}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - EXECUTION SLIPPAGE AUDIT V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'Signal price -> Freqtrade open_rate audit: ENABLED'
Write-Host 'Engine latency: ENABLED'
Write-Host 'Fill-observed latency: ENABLED'
Write-Host ('Telegram critical alert: '+$st.alert_bps+' bps')
Write-Host ('Telegram configured: '+$st.telegram_configured)
Write-Host 'JSONL: /data/astra_slippage_audit.jsonl'
Write-Host 'DRY_RUN fills are explicitly marked simulated.'
Write-Host 'LIVE bridge telemetry installed but LIVE was NOT armed.'
Write-Host 'Trading decisions changed: NO'
Write-Host 'Freqtrade dry_run changed: NO'
Write-Host ('Backup: '+$backup)
