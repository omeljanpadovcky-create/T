$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - NEWS INTELLIGENCE SHADOW V2 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$commit='7c98763654faa699e81f726044fd60f647e12f28'
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
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){throw 'ASTRA project folder not found.'}
Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

Write-Host '[0/11] Preflight current api.py...'
& python -m py_compile (Join-Path $app 'api.py')
if($LASTEXITCODE -ne 0){throw 'Current api.py is invalid. Nothing modified.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-news-intelligence-v3-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('api.py','index.html','context_collector.py','forward_experiment_lab.py','news_analyzer.py','news_outcomes.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_news_intelligence_v3'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/11] Downloading Forward Lab, Context V2, News Intelligence and dashboard...'
$downloads=@{
  'forward_experiment_lab.py'='/astra_forward_experiment_lab/forward_experiment_lab.py'
  'patch_forward_experiment_lab.py'='/astra_forward_experiment_lab/patch_forward_experiment_lab.py'
  'selftest_forward_experiment_lab.py'='/astra_forward_experiment_lab/selftest_forward_experiment_lab.py'
  'context_collector.py'='/astra_context_24_7/context_collector.py'
  'news_analyzer.py'='/astra_news_intelligence/news_analyzer.py'
  'news_outcomes.py'='/astra_news_intelligence/news_outcomes.py'
  'patch_news_intelligence.py'='/astra_news_intelligence/patch_news_intelligence.py'
  'selftest_news_intelligence.py'='/astra_news_intelligence/selftest_news_intelligence.py'
  'index.html'='/index.html'
}
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri ($root+$downloads[$name]) -OutFile (Join-Path $tmp $name)
}

Write-Host '[2/11] Python compile + dashboard marker checks...'
$py=@(
  'forward_experiment_lab.py','patch_forward_experiment_lab.py','selftest_forward_experiment_lab.py',
  'context_collector.py','news_analyzer.py','news_outcomes.py','patch_news_intelligence.py','selftest_news_intelligence.py'
) | ForEach-Object {Join-Path $tmp $_}
& python -m py_compile @py
if($LASTEXITCODE -ne 0){throw 'Downloaded Python compile failed. Local ASTRA not modified.'}
$html=Get-Content (Join-Path $tmp 'index.html') -Raw
foreach($m in @('FORWARD EXPERIMENT LAB','NEWS INTELLIGENCE','refreshNewsIntelligence','localAstraOrigin')){
  if($html -notlike ('*'+$m+'*')){throw ('Dashboard missing marker: '+$m)}
}
Write-Host '[OK] downloaded code valid' -ForegroundColor Green

Write-Host '[3/11] Forward Experiment synthetic self-test...'
Push-Location $tmp
try {
  & python '.\selftest_forward_experiment_lab.py'
  if($LASTEXITCODE -ne 0){throw 'Forward Lab self-test failed. Local ASTRA not modified.'}
} finally {Pop-Location}
Write-Host '[OK] Forward Lab self-test passed' -ForegroundColor Green

Write-Host '[4/11] News Intelligence synthetic self-test...'
$pkg=Join-Path $tmp 'newspkg'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $pkg '__init__.py') -Force | Out-Null
Copy-Item (Join-Path $tmp 'news_analyzer.py') (Join-Path $pkg 'news_analyzer.py') -Force
Copy-Item (Join-Path $tmp 'news_outcomes.py') (Join-Path $pkg 'news_outcomes.py') -Force
Copy-Item (Join-Path $tmp 'selftest_news_intelligence.py') (Join-Path $pkg 'selftest_news_intelligence.py') -Force
Push-Location $tmp
try {
  & python -m newspkg.selftest_news_intelligence
  if($LASTEXITCODE -ne 0){throw 'News Intelligence self-test failed. Local ASTRA not modified.'}
} finally {Pop-Location}
Write-Host '[OK] News Intelligence self-test passed' -ForegroundColor Green

Write-Host '[5/11] Installing modules + dashboard...'
Copy-Item (Join-Path $tmp 'context_collector.py') (Join-Path $app 'context_collector.py') -Force
Copy-Item (Join-Path $tmp 'forward_experiment_lab.py') (Join-Path $app 'forward_experiment_lab.py') -Force
Copy-Item (Join-Path $tmp 'news_analyzer.py') (Join-Path $app 'news_analyzer.py') -Force
Copy-Item (Join-Path $tmp 'news_outcomes.py') (Join-Path $app 'news_outcomes.py') -Force
Copy-Item (Join-Path $tmp 'index.html') (Join-Path $app 'index.html') -Force

Write-Host '[6/11] Patching API...'
try {
  & python (Join-Path $tmp 'patch_forward_experiment_lab.py') $app
  if($LASTEXITCODE -ne 0){throw 'Forward Lab API patch failed.'}
  & python (Join-Path $tmp 'patch_news_intelligence.py') $app
  if($LASTEXITCODE -ne 0){throw 'News Intelligence API patch failed.'}

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'context_collector.py' 'forward_experiment_lab.py' 'news_analyzer.py' 'news_outcomes.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  foreach($name in @('api.py','index.html','context_collector.py','forward_experiment_lab.py','news_analyzer.py','news_outcomes.py')){
    $b=Join-Path $backup $name
    $dst=Join-Path $app $name
    if(Test-Path $b){Copy-Item $b $dst -Force}
    elseif($name -in @('forward_experiment_lab.py','news_analyzer.py','news_outcomes.py')){Remove-Item $dst -ErrorAction SilentlyContinue}
  }
  throw
}
Write-Host '[OK] API patched · trading rules unchanged' -ForegroundColor Green

Write-Host '[7/11] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'docker compose rebuild failed.'}
} finally {Pop-Location}

Write-Host '[8/11] Publishing dashboard into persistent /data...'
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

Write-Host '[9/11] Checking Context RSS + core reports...'
$ctx=$null
for($i=0;$i -lt 15;$i++){
  try{
    $ctx=Invoke-RestMethod 'http://127.0.0.1:8088/context/status' -Headers $headers -TimeoutSec 10
    if($ctx.last_news_at){break}
  }catch{}
  Start-Sleep -Seconds 4
}
if(-not $ctx){throw 'Context status unavailable.'}

$fwd=Invoke-RestMethod 'http://127.0.0.1:8088/forward-experiments/report' -Headers $headers -TimeoutSec 20
$hard=Invoke-RestMethod 'http://127.0.0.1:8088/hardening/status' -Headers $headers -TimeoutSec 10
if($fwd.status -ne 'ok'){throw 'Forward Lab report failed.'}
if($hard.status -ne 'ok'){throw 'Hardening regression detected.'}

Write-Host ('[OK] RSS configured: '+$ctx.rss_feeds+' · sources OK: '+$ctx.news_sources_ok+' · cache: '+$ctx.headline_cache) -ForegroundColor Green
if($ctx.last_news_error){Write-Host ('[WARN] RSS: '+$ctx.last_news_error) -ForegroundColor Yellow}
Write-Host ('[OK] Forward Lab: '+$fwd.mode) -ForegroundColor Green
Write-Host ('[OK] Hardening: '+$hard.status) -ForegroundColor Green

Write-Host '[10/11] Running live Ollama news classification check...'
$refresh=$null
try{
  $refresh=Invoke-RestMethod 'http://127.0.0.1:8088/news-intelligence/refresh-now?limit=2' -Method Post -Headers $headers -TimeoutSec 60
}catch{
  Write-Host ('[WARN] manual News Intelligence refresh: '+$_.Exception.Message) -ForegroundColor Yellow
}
$news=Invoke-RestMethod 'http://127.0.0.1:8088/news-intelligence/report' -Headers $headers -TimeoutSec 20
if($news.status -ne 'ok'){throw 'News Intelligence report failed.'}
Write-Host ('[OK] News analyzer mode: '+$news.analyzer.mode) -ForegroundColor Green
Write-Host ('Ollama: '+$news.analyzer.ollama.status+' · '+$news.analyzer.ollama.model)
Write-Host ('Analyzed headlines: '+$news.analyzer.analysis_ok+' · errors: '+$news.analyzer.analysis_error)
Write-Host ('Dynamic universe: '+(($news.analyzer.universe_assets | ForEach-Object {[string]$_}) -join ', '))
Write-Host ('Time decay half-life: '+$news.analyzer.decay_half_life_minutes+' min')
Write-Host ('Dedup: Jaccard '+$news.analyzer.dedup_jaccard+' · window '+$news.analyzer.dedup_window_minutes+' min · last dropped '+$news.analyzer.last_deduped)
Write-Host ('News forward outcomes closed: '+$news.outcomes.closed)

Write-Host '[11/11] Opening authorized dashboard...'
$launch='http://127.0.0.1:8088/dashboard#token='+[uri]::EscapeDataString($token)
Start-Process $launch

Write-Host ''
Write-Host '======================================================' -ForegroundColor Green
Write-Host ' READY - NEWS INTELLIGENCE SHADOW V2 ' -ForegroundColor Green
Write-Host '======================================================' -ForegroundColor Green
Write-Host ('ASTRA health: '+$health.status)
Write-Host ('RSS feeds: '+$ctx.rss_feeds+' · OK: '+$ctx.news_sources_ok+' · cache: '+$ctx.headline_cache)
Write-Host ('Ollama news model: '+$news.analyzer.ollama.model)
Write-Host ('Analyzed headlines: '+$news.analyzer.analysis_ok)
Write-Host ('News assets: MARKET + dynamic TOP-'+$news.analyzer.universe_assets.Count)
Write-Host ('Time decay: half-life '+$news.analyzer.decay_half_life_minutes+' min')
Write-Host ('Cross-source dedup: ON · Jaccard '+$news.analyzer.dedup_jaccard+' · '+$news.analyzer.dedup_window_minutes+' min window')
Write-Host 'News outcomes: 5m | 10m | 15m'
Write-Host 'PAPER execution changed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'News decision effect: NONE / SHADOW ONLY'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: '+$backup)
