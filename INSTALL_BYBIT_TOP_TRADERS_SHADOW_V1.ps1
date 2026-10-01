
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - BYBIT TOP TRADERS SHADOW V1 ' -ForegroundColor Yellow
Write-Host ' SELENIUM READ-ONLY - PAPER/DRY_RUN ONLY ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$moduleCommit='a1a5659345335f1ea9bc871e84606c3db42196dd'
$patchCommit='514fa0ee739a1c7bd4d3809667e5e06731b365e7'
$collectorCommit='a3a8a61dbb160eb17e899462f2422c1ff5429fdb'
$configCommit='f8e7ae08917622c2db6e2ee3e05263b9f9635095'

$moduleUri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$moduleCommit+'/astra_bybit_toptraders_shadow/bybit_toptraders_shadow.py'
$patchUri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$patchCommit+'/astra_bybit_toptraders_shadow/patch_bybit_toptraders_shadow.py'
$collectorUri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$collectorCommit+'/BYBIT_TOP_TRADERS_COLLECTOR_V1.py'
$configUri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$configCommit+'/BYBIT_TOP_TRADERS.example.json'

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
  if(Test-Path (Join-Path $fallback 'api.py')){ return $fallback }
  return $null
}

function Get-Token {
  $token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
    Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
    ForEach-Object { $_.Substring($_.IndexOf('=')+1) } |
    Select-Object -First 1)
  if(-not $token){ throw 'MYSHKA_BRIDGE_TOKEN not found.' }
  return $token
}

$app=Get-AppFolder
if(-not $app){ throw 'ASTRA project folder not found.' }
$api=Join-Path $app 'api.py'
$moduleDst=Join-Path $app 'bybit_toptraders_shadow.py'
if(-not (Test-Path $api)){ throw 'api.py not found.' }

Write-Host ('Project: '+$app)

Write-Host '[1/8] DRY_RUN preflight...'
$token=Get-Token
$headers=@{'X-MYSHKA-TOKEN'=$token}
$st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
if($st.real_money_execution -ne $false){ throw 'STOP: real_money_execution is not false.' }
if($st.local_dry_run -ne $true){ throw 'STOP: Freqtrade DRY_RUN not confirmed.' }
Write-Host '[OK] DRY_RUN confirmed. Real-money execution OFF.' -ForegroundColor Green

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$apiBackup=$api+'.before-bybit-toptraders-v1-'+$stamp
Copy-Item $api $apiBackup -Force
$moduleBackup=$null
if(Test-Path $moduleDst){
  $moduleBackup=$moduleDst+'.before-bybit-toptraders-v1-'+$stamp
  Copy-Item $moduleDst $moduleBackup -Force
}
Write-Host ('[OK] api.py backup: '+$apiBackup) -ForegroundColor Green

$tmpModule=Join-Path $env:TEMP 'bybit_toptraders_shadow.py'
$tmpPatch=Join-Path $env:TEMP 'patch_bybit_toptraders_shadow.py'
$nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

Write-Host '[2/8] Downloading pinned ASTRA module + patcher...'
Invoke-WebRequest -UseBasicParsing -Uri ($moduleUri+'?x='+$nonce) -OutFile $tmpModule -TimeoutSec 60
Invoke-WebRequest -UseBasicParsing -Uri ($patchUri+'?x='+$nonce) -OutFile $tmpPatch -TimeoutSec 60

Write-Host '[3/8] Installing SHADOW module...'
Copy-Item $tmpModule $moduleDst -Force

Write-Host '[4/8] Patching api.py...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python $tmpPatch $app
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){
  Copy-Item $apiBackup $api -Force
  if($moduleBackup){ Copy-Item $moduleBackup $moduleDst -Force }
  elseif(Test-Path $moduleDst){ Remove-Item $moduleDst -Force }
  throw 'API patch failed; backups restored.'
}

Write-Host '[5/8] Syntax check + ASTRA rebuild...'
Push-Location $app
try {
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python -m py_compile 'bybit_toptraders_shadow.py' 'api.py'
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){
    Copy-Item $apiBackup $api -Force
    throw 'Compile failed; api.py backup restored.'
  }

  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){ throw 'ASTRA rebuild failed.' }
} finally { Pop-Location }

Write-Host '[6/8] Health + endpoint verification...'
$health=$null
for($i=0;$i -lt 35;$i++){
  Start-Sleep -Seconds 2
  try {
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 6
    if($health.status -eq 'ok'){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health failed.' }

$token=Get-Token
$headers=@{'X-MYSHKA-TOKEN'=$token}
$st=Invoke-RestMethod 'http://127.0.0.1:8088/bybit-top-traders/status' -Headers $headers -TimeoutSec 10
Write-Host ('[OK] Shadow state: '+$st.state+' fresh_traders='+$st.fresh_traders) -ForegroundColor Green

Write-Host '[7/8] Installing Selenium on Windows host...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m pip install --user 'selenium>=4.20,<5'
$piprc=$LASTEXITCODE
$ErrorActionPreference=$old
if($piprc -ne 0){
  Write-Host '[WARN] Selenium pip install failed. ASTRA shadow module is installed; collector can be installed later.' -ForegroundColor Yellow
}

Write-Host '[8/8] Downloading collector + config...'
$collectorDst=Join-Path $env:USERPROFILE 'Downloads\BYBIT_TOP_TRADERS_COLLECTOR_V1.py'
$configDst=Join-Path $env:USERPROFILE 'Downloads\BYBIT_TOP_TRADERS.json'
Invoke-WebRequest -UseBasicParsing -Uri ($collectorUri+'?x='+$nonce) -OutFile $collectorDst -TimeoutSec 60
if(-not (Test-Path $configDst)){
  Invoke-WebRequest -UseBasicParsing -Uri ($configUri+'?x='+$nonce) -OutFile $configDst -TimeoutSec 60
  Write-Host ('[NEW] Config: '+$configDst) -ForegroundColor Cyan
} else {
  Write-Host ('[KEEP] Existing config preserved: '+$configDst) -ForegroundColor Cyan
}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' BYBIT TOP TRADERS SHADOW V1 READY ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'Safety:'
Write-Host ' - Selenium is READ-ONLY'
Write-Host ' - Copy/Follow/Buy/Sell buttons are never clicked'
Write-Host ' - ASTRA action/reason are unchanged'
Write-Host ' - Freqtrade DRY_RUN remains ON'
Write-Host ' - Real-money execution remains OFF'
Write-Host ''
Write-Host ('1) Edit: '+$configDst)
Write-Host '2) Replace PASTE_BYBIT_MASTER_TRADER_PROFILE_URL_HERE with the Bybit master-trader profile URL.'
Write-Host '3) Run once:'
Write-Host ('   python "'+$collectorDst+'" --once')
Write-Host '4) Then check consensus:'
Write-Host '   Invoke-RestMethod "http://127.0.0.1:8088/bybit-top-traders/report" -Headers $headers'
Write-Host ''
Write-Host ('api.py backup: '+$apiBackup)
