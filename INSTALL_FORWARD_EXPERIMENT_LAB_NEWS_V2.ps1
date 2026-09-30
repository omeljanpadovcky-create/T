$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FORWARD LAB + NEWS CONTEXT V2 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit='3ee31a925a0bd20b76d4fb2dc4da334a4c8565f0'
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
Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-forward-news-v2-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('api.py','index.html','forward_experiment_lab.py','context_collector.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_forward_news_v2'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/9] Downloading fixed Forward Lab + News Context V2 + dashboard...'
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_forward_experiment_lab/forward_experiment_lab.py') -OutFile (Join-Path $tmp 'forward_experiment_lab.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_forward_experiment_lab/patch_forward_experiment_lab.py') -OutFile (Join-Path $tmp 'patch_forward_experiment_lab.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_forward_experiment_lab/selftest_forward_experiment_lab.py') -OutFile (Join-Path $tmp 'selftest_forward_experiment_lab.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_context_24_7/context_collector.py') -OutFile (Join-Path $tmp 'context_collector.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/index.html') -OutFile (Join-Path $tmp 'index.html')

Write-Host '[2/9] Compile + marker checks...'
& python -m py_compile (Join-Path $tmp 'forward_experiment_lab.py') (Join-Path $tmp 'patch_forward_experiment_lab.py') (Join-Path $tmp 'selftest_forward_experiment_lab.py') (Join-Path $tmp 'context_collector.py')
if($LASTEXITCODE -ne 0){throw 'Python compile failed. Local ASTRA not modified.'}
$html=Get-Content (Join-Path $tmp 'index.html') -Raw
foreach($m in @('FORWARD EXPERIMENT LAB','refreshForwardExperimentLab','NEWS ','localAstraOrigin')){
  if($html -notlike ('*'+$m+'*')){throw ('Dashboard missing marker: '+$m)}
}
Write-Host '[OK] compile + dashboard markers passed' -ForegroundColor Green

Write-Host '[3/9] Synthetic Forward Lab self-test...'
Push-Location $tmp
try {
  & python '.\selftest_forward_experiment_lab.py'
  if($LASTEXITCODE -ne 0){throw 'Forward Lab self-test failed. Local ASTRA not modified.'}
} finally {Pop-Location}
Write-Host '[OK] Forward Lab DB/settlement self-test passed' -ForegroundColor Green

Write-Host '[4/9] Installing modules + dashboard...'
Copy-Item (Join-Path $tmp 'forward_experiment_lab.py') (Join-Path $app 'forward_experiment_lab.py') -Force
Copy-Item (Join-Path $tmp 'context_collector.py') (Join-Path $app 'context_collector.py') -Force
Copy-Item (Join-Path $tmp 'index.html') (Join-Path $app 'index.html') -Force

Write-Host '[5/9] Patching API with Forward Lab...'
try {
  & python (Join-Path $tmp 'patch_forward_experiment_lab.py') $app
  if($LASTEXITCODE -ne 0){throw 'Forward Experiment API patch failed.'}
  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'forward_experiment_lab.py' 'context_collector.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  foreach($name in @('api.py','index.html','forward_experiment_lab.py','context_collector.py')){
    $b=Join-Path $backup $name
    if(Test-Path $b){Copy-Item $b (Join-Path $app $name) -Force}
    elseif($name -eq 'forward_experiment_lab.py'){Remove-Item (Join-Path $app $name) -ErrorAction SilentlyContinue}
  }
  throw
}
Write-Host '[OK] API patched · PAPER rules unchanged' -ForegroundColor Green

Write-Host '[6/9] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'docker compose rebuild failed.'}
} finally {Pop-Location}

Write-Host '[7/9] Publishing dashboard into /data...'
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

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

Write-Host '[8/9] Checking Forward Lab + Hardening...'
$lab=Invoke-RestMethod 'http://127.0.0.1:8088/forward-experiments/report' -Headers $headers -TimeoutSec 20
$hard=Invoke-RestMethod 'http://127.0.0.1:8088/hardening/status' -Headers $headers -TimeoutSec 10
if($lab.status -ne 'ok'){throw 'Forward Lab report failed.'}
if($hard.status -ne 'ok'){throw 'Hardening regression detected.'}
Write-Host ('[OK] Forward Lab: '+$lab.mode) -ForegroundColor Green
Write-Host ('[OK] X-Check audit: '+$lab.xcheck_definition.audit) -ForegroundColor Green
Write-Host ('[OK] Hardening: '+$hard.status) -ForegroundColor Green

Write-Host '[9/9] Checking News Context V2...'
$ctx=$null
for($i=0;$i -lt 12;$i++){
  try{
    $ctx=Invoke-RestMethod 'http://127.0.0.1:8088/context/status' -Headers $headers -TimeoutSec 10
    if($ctx.last_news_at -and (($ctx.news_sources_ok -gt 0) -or ($ctx.news_sources_failed -gt 0))){break}
  }catch{}
  Start-Sleep -Seconds 5
}
if(-not $ctx){throw 'Context status unavailable.'}

Write-Host ('Context running: '+$ctx.running)
Write-Host ('RSS feeds configured: '+$ctx.rss_feeds)
Write-Host ('News sources OK: '+$ctx.news_sources_ok)
Write-Host ('News sources failed: '+$ctx.news_sources_failed)
Write-Host ('Headline cache: '+$ctx.headline_cache)
Write-Host ('News lookback: '+$ctx.news_lookback_minutes+' min')
if($ctx.last_news_error){
  Write-Host ('News warning: '+$ctx.last_news_error) -ForegroundColor Yellow
}
if([int]$ctx.news_sources_ok -gt 0 -and [int]$ctx.headline_cache -gt 0){
  Write-Host '[OK] RSS NEWS IS FLOWING' -ForegroundColor Green
}else{
  Write-Host '[WARN] News collector installed, but no live RSS headlines were confirmed in this run.' -ForegroundColor Yellow
}

$launch='http://127.0.0.1:8088/dashboard#token='+[uri]::EscapeDataString($token)
Start-Process $launch

Write-Host ''
Write-Host '======================================================' -ForegroundColor Green
Write-Host ' READY - FORWARD LAB + NEWS CONTEXT V2 ' -ForegroundColor Green
Write-Host '======================================================' -ForegroundColor Green
Write-Host ('ASTRA health: '+$health.status)
Write-Host ('Forward mode: '+$lab.mode)
Write-Host ('Forward start: '+([DateTimeOffset]::FromUnixTimeSeconds([int64][math]::Floor([double]$lab.forward_started_at)).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss')))
Write-Host ('X-Check direction audit: '+$lab.xcheck_definition.audit)
Write-Host 'Forward experiments: NEUTRAL OFF | AGREE vs CONFLICT | TECH 3/4 vs 4/4 | EDGE bands | costs'
Write-Host 'News: Cointelegraph + CoinDesk + Decrypt RSS/Atom · SHADOW'
Write-Host 'PAPER execution changed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'News decision effect: NONE / SHADOW ONLY'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: '+$backup)
