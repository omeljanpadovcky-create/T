$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - INSTALL FREQTRADE LIVE BRIDGE V1 ' -ForegroundColor Yellow
Write-Host ' INSTALLS LIVE-CAPABLE CODE, DOES NOT ARM REAL MONEY ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='1828e6f8384defeaf53b970f510b88a968af84f8'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/' + $bundleCommit

$app=$null
try {
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
} catch {}

if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback 'api.py')){$app=$fallback}
}
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){throw 'ASTRA project folder not found.'}
if(-not (Test-Path (Join-Path $app 'live_dry_run.py'))){throw 'live_dry_run.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-freqtrade-live-bridge-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','freqtrade_live_bridge.py')){
  $src=Join-Path $app $f
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $f) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_freqtrade_live_bridge_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads=@{
  'freqtrade_live_bridge.py'=$root+'/astra_freqtrade_live_bridge/freqtrade_live_bridge.py'
  'patch_freqtrade_live_bridge.py'=$root+'/astra_freqtrade_live_bridge/patch_freqtrade_live_bridge.py'
  'selftest_freqtrade_live_bridge.py'=$root+'/astra_freqtrade_live_bridge/selftest_freqtrade_live_bridge.py'
}

Write-Host '[1/7] Downloading pinned LIVE bridge bundle...'
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name)
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/7] Python compile...'
$py=@(
  (Join-Path $tmp 'freqtrade_live_bridge.py'),
  (Join-Path $tmp 'patch_freqtrade_live_bridge.py'),
  (Join-Path $tmp 'selftest_freqtrade_live_bridge.py')
)
& python -m py_compile @py
if($LASTEXITCODE -ne 0){throw 'Downloaded LIVE bridge syntax invalid. Local ASTRA not modified.'}
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[3/7] Installing module + api.py patch...'
try {
  Copy-Item (Join-Path $tmp 'freqtrade_live_bridge.py') (Join-Path $app 'freqtrade_live_bridge.py') -Force
  & python (Join-Path $tmp 'patch_freqtrade_live_bridge.py') $app
  if($LASTEXITCODE -ne 0){throw 'LIVE bridge API patch failed.'}

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'freqtrade_live_bridge.py' 'live_dry_run.py'
    if($LASTEXITCODE -ne 0){throw 'Final ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  foreach($f in @('api.py','freqtrade_live_bridge.py')){
    $old=Join-Path $backup $f
    $dst=Join-Path $app $f
    if(Test-Path $old){Copy-Item $old $dst -Force}
    elseif($f -eq 'freqtrade_live_bridge.py' -and (Test-Path $dst)){Remove-Item $dst -Force}
  }
  Write-Host '[ROLLBACK] Restored pre-install files.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] LIVE bridge installed and compiled.' -ForegroundColor Green

Write-Host '[4/7] Rebuilding ASTRA only...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'ASTRA rebuild failed.'}
} finally {Pop-Location}

Write-Host '[5/7] Waiting for /health...'
$health=$null
for($i=0;$i -lt 45;$i++){
  Start-Sleep -Seconds 2
  try {
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok' -and $health.freqtrade_live_bridge){break}
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health check failed.'}
if(-not $health.freqtrade_live_bridge){throw 'LIVE bridge missing from /health.'}
Write-Host '[OK] ASTRA health + LIVE bridge present.' -ForegroundColor Green

Write-Host '[6/7] Checking authenticated LIVE bridge status...'
$token=$null
try {
  $token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
    Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} |
    Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
} catch {}
$headers=@{}
if($token){$headers['X-MYSHKA-TOKEN']=$token}
$status=Invoke-RestMethod 'http://127.0.0.1:8088/freqtrade-live/status' -Headers $headers -TimeoutSec 10

Write-Host '[7/7] Summary...'
Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - FREQTRADE LIVE BRIDGE V1 INSTALLED ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Mode: '+$status.mode)
Write-Host ('Local live enabled: '+$status.local_live_enabled)
Write-Host ('Credentials present: '+$status.credentials_present)
Write-Host ('Max stake USDT: '+$status.max_stake_usdt)
Write-Host ('Max leverage: '+$status.max_leverage)
Write-Host ''
Write-Host 'IMPORTANT:'
Write-Host ' - This installer DID NOT set dry_run=false'
Write-Host ' - This installer DID NOT arm real-money execution'
Write-Host ' - This installer DID NOT send an order'
Write-Host ' - Use ARM_FREQTRADE_LIVE_V1.ps1 only when you explicitly choose to activate live'
Write-Host ('Backup: '+$backup)
