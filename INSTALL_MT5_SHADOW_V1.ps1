$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - INSTALL MT5 SHADOW V1 ' -ForegroundColor Yellow
Write-Host ' WINDOWS MT5 COLLECTOR + ASTRA READ-ONLY XCHECK ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='236003f78b03cd538b1d9e8eddb200d0a9c06f7b'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$bundleCommit

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

Set-Location $app
if(-not (Test-Path '.env.live-armed')){throw '.env.live-armed not found.'}
if(-not (Test-Path 'telegram_notify.py')){throw 'telegram_notify.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-mt5-shadow-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','telegram_notify.py','mt5_shadow_agent.py','mt5_shadow_collector.py','.env.live-armed','START_MT5_SHADOW_V1.ps1','STOP_MT5_SHADOW_V1.ps1')){
  $src=Join-Path $app $f
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $f) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_mt5_shadow_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

function Get-PinnedRawFile {
  param([string]$RepoPath,[string]$OutFile)
  $uri=$root+'/'+$RepoPath+'?x='+[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
  Invoke-WebRequest -UseBasicParsing -Uri $uri -Headers @{
    'User-Agent'='MYSHKA-ASTRA-MT5-Shadow'
    'Cache-Control'='no-cache, no-store, max-age=0'
    'Pragma'='no-cache'
  } -OutFile $OutFile -TimeoutSec 60
}

Write-Host '[1/10] Download pinned MT5 Shadow bundle...'
Get-PinnedRawFile 'astra_mt5_shadow/mt5_shadow_agent.py' (Join-Path $tmp 'mt5_shadow_agent.py')
Get-PinnedRawFile 'astra_mt5_shadow/mt5_shadow_collector.py' (Join-Path $tmp 'mt5_shadow_collector.py')
Get-PinnedRawFile 'astra_mt5_shadow/selftest_mt5_shadow_agent.py' (Join-Path $tmp 'selftest_mt5_shadow_agent.py')
Get-PinnedRawFile 'astra_mt5_shadow/selftest_mt5_shadow_collector.py' (Join-Path $tmp 'selftest_mt5_shadow_collector.py')
Get-PinnedRawFile 'astra_mt5_shadow/patch_mt5_shadow.py' (Join-Path $tmp 'patch_mt5_shadow.py')
Get-PinnedRawFile 'START_MT5_SHADOW_V1.ps1' (Join-Path $tmp 'START_MT5_SHADOW_V1.ps1')
Get-PinnedRawFile 'STOP_MT5_SHADOW_V1.ps1' (Join-Path $tmp 'STOP_MT5_SHADOW_V1.ps1')
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/10] Static READ-ONLY checks + Python compile...'
$collectorSrc=Get-Content (Join-Path $tmp 'mt5_shadow_collector.py') -Raw -Encoding UTF8
$forbidden=('order'+'_send')
if($collectorSrc -match [regex]::Escape($forbidden)){throw 'HARD STOP: MT5 collector contains a forbidden trade execution call.'}
foreach($marker in @('copy_rates_from_pos','symbol_info_tick','read_only')){
  if($collectorSrc -notlike ('*'+$marker+'*')){throw ('Missing collector marker: '+$marker)}
}
$py=@(
  (Join-Path $tmp 'mt5_shadow_agent.py'),
  (Join-Path $tmp 'mt5_shadow_collector.py'),
  (Join-Path $tmp 'selftest_mt5_shadow_agent.py'),
  (Join-Path $tmp 'selftest_mt5_shadow_collector.py'),
  (Join-Path $tmp 'patch_mt5_shadow.py')
)
& python -m py_compile @py
if($LASTEXITCODE -ne 0){throw 'MT5 Shadow bundle compile failed.'}
Write-Host '[OK] READ-ONLY markers + syntax valid.' -ForegroundColor Green

Write-Host '[3/10] Run isolated ASTRA agent self-test...'
Push-Location $tmp
try {
  & python '.\selftest_mt5_shadow_agent.py'
  if($LASTEXITCODE -ne 0){throw 'MT5 Shadow Agent self-test failed.'}
  & python '.\selftest_mt5_shadow_collector.py'
  if($LASTEXITCODE -ne 0){throw 'MT5 Shadow Collector synthetic self-test failed.'}
} finally {Pop-Location}
Write-Host '[OK] Synthetic self-tests passed.' -ForegroundColor Green

Write-Host '[4/10] Ensure MetaTrader5 Python package on Windows...'
$mt5Pkg=$true
& python -c "import MetaTrader5; print('MetaTrader5 package already installed')" 2>$null
if($LASTEXITCODE -ne 0){$mt5Pkg=$false}
if(-not $mt5Pkg){
  & python -m pip install --upgrade MetaTrader5
  if($LASTEXITCODE -ne 0){throw 'Could not install MetaTrader5 Python package.'}
}
& python -c "import MetaTrader5 as mt5; print('MetaTrader5 version',mt5.__version__)"
if($LASTEXITCODE -ne 0){throw 'MetaTrader5 package import failed after install.'}

Write-Host '[5/10] Configure local MT5 Shadow token/env...'
$envLines=Get-Content '.env.live-armed'
$oldToken=$envLines | Where-Object {$_ -match '^MT5_SHADOW_TOKEN='} | Select-Object -First 1
if($oldToken){
  $token=($oldToken -replace '^MT5_SHADOW_TOKEN=','').Trim().Trim('"').Trim("'")
} else {
  $bytes=New-Object byte[] 32
  $rng=[System.Security.Cryptography.RandomNumberGenerator]::Create()
  $rng.GetBytes($bytes)
  $rng.Dispose()
  $token=([BitConverter]::ToString($bytes)).Replace('-','').ToLowerInvariant()
}
$envLines=@($envLines | Where-Object {
  $_ -notmatch '^MT5_SHADOW_BASE_URL=' -and
  $_ -notmatch '^MT5_SHADOW_TOKEN=' -and
  $_ -notmatch '^MT5_SHADOW_HTTP_TIMEOUT_SEC=' -and
  $_ -notmatch '^MT5_SHADOW_AGENT_CACHE_SEC=' -and
  $_ -notmatch '^MT5_SHADOW_AGENT_MAX_AGE_SEC=' -and
  $_ -notmatch '^MT5_SHADOW_HORIZONS_SEC='
})
$envLines += 'MT5_SHADOW_BASE_URL=http://host.docker.internal:8115'
$envLines += ('MT5_SHADOW_TOKEN='+$token)
$envLines += 'MT5_SHADOW_HTTP_TIMEOUT_SEC=3'
$envLines += 'MT5_SHADOW_AGENT_CACHE_SEC=8'
$envLines += 'MT5_SHADOW_AGENT_MAX_AGE_SEC=60'
$envLines += 'MT5_SHADOW_HORIZONS_SEC=300,600,900'
$envLines | Set-Content '.env.live-armed' -Encoding ASCII
Write-Host '[OK] MT5 Shadow env configured. Token not displayed.' -ForegroundColor Green

Write-Host '[6/10] Install files + patch ASTRA/Telegram...'
Copy-Item (Join-Path $tmp 'mt5_shadow_agent.py') (Join-Path $app 'mt5_shadow_agent.py') -Force
Copy-Item (Join-Path $tmp 'mt5_shadow_collector.py') (Join-Path $app 'mt5_shadow_collector.py') -Force
Copy-Item (Join-Path $tmp 'START_MT5_SHADOW_V1.ps1') (Join-Path $app 'START_MT5_SHADOW_V1.ps1') -Force
Copy-Item (Join-Path $tmp 'STOP_MT5_SHADOW_V1.ps1') (Join-Path $app 'STOP_MT5_SHADOW_V1.ps1') -Force

try {
  & python (Join-Path $tmp 'patch_mt5_shadow.py') $app
  if($LASTEXITCODE -ne 0){throw 'MT5 Shadow ASTRA patch failed.'}
  & python -m py_compile 'api.py' 'telegram_notify.py' 'mt5_shadow_agent.py' 'mt5_shadow_collector.py'
  if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
} catch {
  foreach($f in @('api.py','telegram_notify.py','mt5_shadow_agent.py','mt5_shadow_collector.py','.env.live-armed','START_MT5_SHADOW_V1.ps1','STOP_MT5_SHADOW_V1.ps1')){
    $old=Join-Path $backup $f
    $dst=Join-Path $app $f
    if(Test-Path $old){Copy-Item $old $dst -Force}
  }
  throw
}
Write-Host '[OK] ASTRA + Telegram patched.' -ForegroundColor Green

Write-Host '[7/10] Start Windows MT5 Shadow Collector...'
& powershell -ExecutionPolicy Bypass -File (Join-Path $app 'START_MT5_SHADOW_V1.ps1')
if($LASTEXITCODE -ne 0){throw 'MT5 Shadow Collector start failed.'}

Write-Host '[8/10] Rebuild/recreate ASTRA only...'
$ErrorActionPreference='Continue'
docker compose up -d --build --force-recreate astra
$dockerRc=$LASTEXITCODE
$ErrorActionPreference='Stop'
if($dockerRc -ne 0){throw 'ASTRA rebuild failed.'}

Write-Host '[9/10] Verify Docker -> Windows collector + ASTRA API...'
$dockerProbe=cmd /c 'docker exec myshka-astra python -c "import urllib.request; print(urllib.request.urlopen(''http://host.docker.internal:8115/health'',timeout=5).read().decode())" 2>nul'
if(-not ($dockerProbe -match '"status":"ok"')){throw ('Docker cannot reach MT5 Shadow Collector: '+($dockerProbe -join ' '))}

$ready=$false
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 2
  try {
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($h.status -eq 'ok' -and $h.mt5_shadow){$ready=$true;break}
  } catch {}
}
if(-not $ready){throw 'ASTRA health did not expose mt5_shadow.'}

$bridgeToken=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $bridgeToken){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$bridgeToken}
$st=Invoke-RestMethod 'http://127.0.0.1:8088/mt5-shadow/status' -Headers $headers -TimeoutSec 10
$rep=Invoke-RestMethod 'http://127.0.0.1:8088/mt5-shadow/report' -Headers $headers -TimeoutSec 10

Write-Host '[10/10] Ready.'
Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - MT5 / LIBERTEX SHADOW V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Mode: '+$st.mode)
Write-Host ('Collector URL: '+$st.base_url)
Write-Host ('Token present in ASTRA: '+$st.token_present)
Write-Host ('Horizons: '+($st.horizons_sec -join ',')+' sec')
Write-Host 'Telegram: MT5 XCHECK + MT5 SOURCE + MT5 STACK'
Write-Host 'Forward: MT5 AGREE / CONFLICT / NEUTRAL / NO_DATA'
Write-Host 'Execution through MT5: DISABLED / NOT IMPLEMENTED'
Write-Host 'Freqtrade/PAPER/LIVE decision logic: UNCHANGED'
Write-Host ('Backup: '+$backup)
