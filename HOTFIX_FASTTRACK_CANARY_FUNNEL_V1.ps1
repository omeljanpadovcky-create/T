$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FASTTRACK CANARY FUNNEL HOTFIX V1 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$commit='aa18f33f857710e7e8489ffa9f8a83d684d0c635'
$uri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$commit+'/astra_fasttrack_canary/fasttrack_paper_canary.py'
$env:COMPOSE_ANSI='never'
$env:BUILDKIT_PROGRESS='plain'

$app=$null
try{
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
}catch{}
if(-not $app){throw 'ASTRA project folder not found.'}

$dst=Join-Path $app 'fasttrack_paper_canary.py'
if(-not (Test-Path $dst)){throw 'fasttrack_paper_canary.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=$dst+'.before-funnel-v1-'+$stamp
Copy-Item $dst $backup -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_fasttrack_canary_funnel_v1.py'
$nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

Write-Host '[1/5] Downloading telemetry hotfix...'
Invoke-WebRequest -UseBasicParsing -Uri ($uri+'?x='+$nonce) -Headers @{
  'User-Agent'='MYSHKA-ASTRA-FastTrackFunnel'
  'Cache-Control'='no-cache, no-store, max-age=0'
  'Pragma'='no-cache'
} -OutFile $tmp -TimeoutSec 60

$src=Get-Content $tmp -Raw -Encoding UTF8
foreach($m in @('live_funnel','scan_calls','triple_eligible','last_stage')){
  if($src -notlike ('*'+$m+'*')){throw ('Missing telemetry marker: '+$m)}
}

Write-Host '[2/5] Compile...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile $tmp
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'Telemetry module compile failed.'}

Write-Host '[3/5] Install module...'
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
    throw 'Local compile failed. Previous module restored.'
  }

  Write-Host '[4/5] Rebuilding ASTRA...'
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){
    Copy-Item $backup $dst -Force
    throw 'ASTRA rebuild failed. Previous module restored.'
  }
}finally{Pop-Location}

Write-Host '[5/5] Verify status...'
$ready=$false
for($i=0;$i -lt 35;$i++){
  Start-Sleep -Seconds 2
  try{
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 6
    if($h.status -eq 'ok'){$ready=$true;break}
  }catch{}
}
if(-not $ready){throw 'ASTRA did not become healthy.'}

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  ForEach-Object { $_.Substring($_.IndexOf('=')+1) } |
  Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

$st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
if(-not $st.live_funnel){throw 'live_funnel missing after hotfix.'}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - FASTTRACK CANARY FUNNEL V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
$st.live_funnel | ConvertTo-Json -Depth 6
Write-Host ''
Write-Host 'LIVE armed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host ('Backup: '+$backup)
