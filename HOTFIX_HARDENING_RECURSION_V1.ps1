$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - HOTFIX HARDENING RECURSION V1 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$commit='836b63f9afb6323e4a708b7f8b7caf25dbe185b6'
$root='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$commit

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
if(-not $app){throw 'ASTRA project folder not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-hardening-recursion-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$dst=Join-Path $app 'system_hardening.py'
if(Test-Path $dst){Copy-Item $dst (Join-Path $backup 'system_hardening.py') -Force}

$tmp=Join-Path $env:TEMP 'myshka_hardening_recursion_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/6] Downloading fixed Hardening module + self-test...'
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_hardening/system_hardening.py') -OutFile (Join-Path $tmp 'system_hardening.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_hardening/selftest_hardening_recursion.py') -OutFile (Join-Path $tmp 'selftest_hardening_recursion.py')

Write-Host '[2/6] Python compile check...'
& python -m py_compile (Join-Path $tmp 'system_hardening.py') (Join-Path $tmp 'selftest_hardening_recursion.py')
if($LASTEXITCODE -ne 0){throw 'Python compile failed. Local ASTRA not modified.'}
Write-Host '[OK] compile passed' -ForegroundColor Green

Write-Host '[3/6] Isolated recursion regression self-test...'
Push-Location $tmp
try {
  & python '.\selftest_hardening_recursion.py'
  if($LASTEXITCODE -ne 0){throw 'Hardening recursion self-test failed. Local ASTRA not modified.'}
} finally {Pop-Location}
Write-Host '[OK] self-test passed' -ForegroundColor Green

Write-Host '[4/6] Installing fixed system_hardening.py...'
Copy-Item (Join-Path $tmp 'system_hardening.py') $dst -Force
Push-Location $app
try {
  & python -m py_compile 'system_hardening.py' 'api.py'
  if($LASTEXITCODE -ne 0){
    if(Test-Path (Join-Path $backup 'system_hardening.py')){Copy-Item (Join-Path $backup 'system_hardening.py') $dst -Force}
    throw 'Final compile failed; previous Hardening module restored.'
  }
} finally {Pop-Location}
Write-Host '[OK] module installed' -ForegroundColor Green

Write-Host '[5/6] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'docker compose rebuild failed.'}
} finally {Pop-Location}

$health=$null
for($i=0;$i -lt 45;$i++){
  Start-Sleep -Seconds 2
  try{
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed after rebuild.'}

Write-Host '[6/6] Timing authenticated /hardening/status...'
$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}
$sw=[System.Diagnostics.Stopwatch]::StartNew()
$r=Invoke-RestMethod 'http://127.0.0.1:8088/hardening/status' -Headers $headers -TimeoutSec 10
$sw.Stop()
if($r.status -ne 'ok'){throw 'Hardening endpoint did not return status=ok.'}

Write-Host ''
Write-Host '======================================================' -ForegroundColor Green
Write-Host ' READY - HARDENING RECURSION FIXED ' -ForegroundColor Green
Write-Host '======================================================' -ForegroundColor Green
Write-Host ('ASTRA health: '+$health.status)
Write-Host ('Hardening status: '+$r.status)
Write-Host ('Hardening response time: '+[math]::Round($sw.Elapsed.TotalSeconds,3)+' sec')
Write-Host 'Recursion init()->status()->init(): REMOVED'
Write-Host 'Trading logic changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: '+$backup)
