$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - INSTALL FORWARD EXPERIMENT LAB V1 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$commit='cf1be11c44f9b0de8bdccd2a18c00f12768bac1f'
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
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){
  throw 'ASTRA project folder not found.'
}
Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-forward-experiment-lab-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('api.py','index.html','forward_experiment_lab.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_forward_experiment_lab_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/8] Downloading module, patcher, self-test and dashboard...'
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_forward_experiment_lab/forward_experiment_lab.py') -OutFile (Join-Path $tmp 'forward_experiment_lab.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_forward_experiment_lab/patch_forward_experiment_lab.py') -OutFile (Join-Path $tmp 'patch_forward_experiment_lab.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_forward_experiment_lab/selftest_forward_experiment_lab.py') -OutFile (Join-Path $tmp 'selftest_forward_experiment_lab.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/index.html') -OutFile (Join-Path $tmp 'index.html')

Write-Host '[2/8] Compile checks...'
& python -m py_compile (Join-Path $tmp 'forward_experiment_lab.py') (Join-Path $tmp 'patch_forward_experiment_lab.py') (Join-Path $tmp 'selftest_forward_experiment_lab.py')
if($LASTEXITCODE -ne 0){throw 'Forward Lab Python compile failed. Local ASTRA not modified.'}
$html=Get-Content (Join-Path $tmp 'index.html') -Raw
foreach($m in @('FORWARD EXPERIMENT LAB','refreshForwardExperimentLab','localAstraOrigin','POSTV2_300')){
  if($html -notlike ('*'+$m+'*')){throw ('Dashboard missing marker: '+$m)}
}
Write-Host '[OK] compile + dashboard markers passed' -ForegroundColor Green

Write-Host '[3/8] Synthetic Forward Lab self-test...'
Push-Location $tmp
try {
  & python '.\selftest_forward_experiment_lab.py'
  if($LASTEXITCODE -ne 0){throw 'Forward Lab self-test failed. Local ASTRA not modified.'}
} finally {Pop-Location}
Write-Host '[OK] synthetic DB + settlement self-test passed' -ForegroundColor Green

Write-Host '[4/8] Installing module + dashboard and patching API...'
Copy-Item (Join-Path $tmp 'forward_experiment_lab.py') (Join-Path $app 'forward_experiment_lab.py') -Force
Copy-Item (Join-Path $tmp 'index.html') (Join-Path $app 'index.html') -Force
try {
  & python (Join-Path $tmp 'patch_forward_experiment_lab.py') $app
  if($LASTEXITCODE -ne 0){throw 'Forward Experiment API patch failed.'}
  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'forward_experiment_lab.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  if(Test-Path (Join-Path $backup 'api.py')){Copy-Item (Join-Path $backup 'api.py') (Join-Path $app 'api.py') -Force}
  if(Test-Path (Join-Path $backup 'index.html')){Copy-Item (Join-Path $backup 'index.html') (Join-Path $app 'index.html') -Force}
  if(Test-Path (Join-Path $backup 'forward_experiment_lab.py')){
    Copy-Item (Join-Path $backup 'forward_experiment_lab.py') (Join-Path $app 'forward_experiment_lab.py') -Force
  } else {
    Remove-Item (Join-Path $app 'forward_experiment_lab.py') -ErrorAction SilentlyContinue
  }
  throw
}
Write-Host '[OK] API patched without changing trading decisions' -ForegroundColor Green

Write-Host '[5/8] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'docker compose rebuild failed.'}
} finally {Pop-Location}

Write-Host '[6/8] Publishing dashboard to persistent /data...'
docker cp (Join-Path $tmp 'index.html') 'myshka-astra:/data/myshka_dashboard.html'
if($LASTEXITCODE -ne 0){throw 'docker cp dashboard failed.'}

$health=$null
for($i=0;$i -lt 45;$i++){
  Start-Sleep -Seconds 2
  try{
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed after rebuild.'}

Write-Host '[7/8] Checking authenticated Forward Lab endpoints...'
$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

$status=Invoke-RestMethod 'http://127.0.0.1:8088/forward-experiments/status' -Headers $headers -TimeoutSec 10
$report=Invoke-RestMethod 'http://127.0.0.1:8088/forward-experiments/report' -Headers $headers -TimeoutSec 20
$hard=Invoke-RestMethod 'http://127.0.0.1:8088/hardening/status' -Headers $headers -TimeoutSec 10
if($report.status -ne 'ok'){throw 'Forward Experiment report did not return status=ok.'}
if($hard.status -ne 'ok'){throw 'Hardening regression detected.'}

Write-Host ('[OK] Forward Lab: '+$report.mode) -ForegroundColor Green
Write-Host ('[OK] X-Check audit: '+$report.xcheck_definition.audit) -ForegroundColor Green
Write-Host ('[OK] Hardening: '+$hard.status) -ForegroundColor Green

Write-Host '[8/8] Opening authorized local dashboard...'
$launch='http://127.0.0.1:8088/dashboard#token='+[uri]::EscapeDataString($token)
Start-Process $launch

Write-Host ''
Write-Host '======================================================' -ForegroundColor Green
Write-Host ' READY - FORWARD EXPERIMENT LAB V1 ' -ForegroundColor Green
Write-Host '======================================================' -ForegroundColor Green
Write-Host ('ASTRA health: '+$health.status)
Write-Host ('Forward mode: '+$report.mode)
Write-Host ('Forward start: '+([DateTimeOffset]::FromUnixTimeSeconds([int64][math]::Floor([double]$report.forward_started_at)).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss')))
Write-Host ('Horizons: '+(($report.horizons_sec | ForEach-Object {[string]$_}) -join ', ')+' sec')
Write-Host ('Cluster window: '+$report.cluster_sec+' sec')
Write-Host ('X-Check direction audit: '+$report.xcheck_definition.audit)
Write-Host 'Experiments: NEUTRAL OFF | AGREE vs CONFLICT | TECH 3/4 vs 4/4 | EDGE bands | costs'
Write-Host 'PAPER execution changed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'Extra market API calls: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: '+$backup)
