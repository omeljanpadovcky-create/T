$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - RESEARCH + READINESS V4 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='2ab65c0bd15489b4e382ab615b6bd79e3fd50621'
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
if(-not $app -or -not (Test-Path (Join-Path $app 'api.py'))){
  throw 'ASTRA project folder not found.'
}
Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green

Write-Host '[0/14] Preflight current api.py...'
& python -m py_compile (Join-Path $app 'api.py')
if($LASTEXITCODE -ne 0){throw 'Current api.py is invalid. Nothing modified.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-research-readiness-v4-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @(
  'api.py','index.html','context_collector.py','forward_experiment_lab.py',
  'news_analyzer.py','news_outcomes.py','news_research_controls.py'
)){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_research_readiness_v4'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/14] Downloading V4 bundle...'
$downloads=@{
  'forward_experiment_lab.py'='/astra_forward_experiment_lab/forward_experiment_lab.py'
  'patch_forward_experiment_lab.py'='/astra_forward_experiment_lab/patch_forward_experiment_lab.py'
  'selftest_forward_experiment_lab.py'='/astra_forward_experiment_lab/selftest_forward_experiment_lab.py'
  'context_collector.py'='/astra_context_24_7/context_collector.py'
  'news_analyzer.py'='/astra_news_intelligence/news_analyzer.py'
  'news_outcomes.py'='/astra_news_intelligence/news_outcomes.py'
  'patch_news_intelligence.py'='/astra_news_intelligence/patch_news_intelligence.py'
  'selftest_news_intelligence.py'='/astra_news_intelligence/selftest_news_intelligence.py'
  'news_research_controls.py'='/astra_news_intelligence/news_research_controls.py'
  'patch_news_research_controls.py'='/astra_news_intelligence/patch_news_research_controls.py'
  'selftest_news_research_controls.py'='/astra_news_intelligence/selftest_news_research_controls.py'
  'index.html'='/index.html'
}
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri ($root+$downloads[$name]) -OutFile (Join-Path $tmp $name)
}

Write-Host '[2/14] Compile + dashboard marker checks...'
$py=@(
  'forward_experiment_lab.py','patch_forward_experiment_lab.py','selftest_forward_experiment_lab.py',
  'context_collector.py','news_analyzer.py','news_outcomes.py','patch_news_intelligence.py',
  'selftest_news_intelligence.py','news_research_controls.py','patch_news_research_controls.py',
  'selftest_news_research_controls.py'
) | ForEach-Object {Join-Path $tmp $_}
& python -m py_compile @py
if($LASTEXITCODE -ne 0){throw 'Downloaded Python compile failed. Local ASTRA not modified.'}
$html=Get-Content (Join-Path $tmp 'index.html') -Raw
foreach($m in @(
  'FORWARD EXPERIMENT LAB','NEWS INTELLIGENCE','NEWS RESEARCH CONTROL',
  'Source Reliability','Per-asset News Lag','refreshLiveReadiness','localAstraOrigin'
)){
  if($html -notlike ('*'+$m+'*')){throw ('Dashboard missing marker: '+$m)}
}
Write-Host '[OK] downloaded code + dashboard markers valid' -ForegroundColor Green

Write-Host '[3/14] Forward Experiment self-test...'
Push-Location $tmp
try {
  & python '.\selftest_forward_experiment_lab.py'
  if($LASTEXITCODE -ne 0){throw 'Forward Lab self-test failed. Local ASTRA not modified.'}
} finally {Pop-Location}
Write-Host '[OK] Forward Lab self-test passed' -ForegroundColor Green

Write-Host '[4/14] News Intelligence V4 self-test...'
$pkg=Join-Path $tmp 'newspkg'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $pkg '__init__.py') -Force | Out-Null
foreach($name in @('news_analyzer.py','news_outcomes.py','selftest_news_intelligence.py','news_research_controls.py','selftest_news_research_controls.py')){
  Copy-Item (Join-Path $tmp $name) (Join-Path $pkg $name) -Force
}
Push-Location $tmp
try {
  & python -m newspkg.selftest_news_intelligence
  if($LASTEXITCODE -ne 0){throw 'News Intelligence self-test failed. Local ASTRA not modified.'}
} finally {Pop-Location}
Write-Host '[OK] News Intelligence self-test passed' -ForegroundColor Green

Write-Host '[5/14] Research Controls / Readiness self-test...'
Push-Location $tmp
try {
  & python -m newspkg.selftest_news_research_controls
  if($LASTEXITCODE -ne 0){throw 'Research Controls self-test failed. Local ASTRA not modified.'}
} finally {Pop-Location}
Write-Host '[OK] Research Controls self-test passed' -ForegroundColor Green

Write-Host '[6/14] Installing modules + dashboard...'
Copy-Item (Join-Path $tmp 'context_collector.py') (Join-Path $app 'context_collector.py') -Force
Copy-Item (Join-Path $tmp 'forward_experiment_lab.py') (Join-Path $app 'forward_experiment_lab.py') -Force
Copy-Item (Join-Path $tmp 'news_analyzer.py') (Join-Path $app 'news_analyzer.py') -Force
Copy-Item (Join-Path $tmp 'news_outcomes.py') (Join-Path $app 'news_outcomes.py') -Force
Copy-Item (Join-Path $tmp 'news_research_controls.py') (Join-Path $app 'news_research_controls.py') -Force
Copy-Item (Join-Path $tmp 'index.html') (Join-Path $app 'index.html') -Force

Write-Host '[7/14] Patching API...'
try {
  & python (Join-Path $tmp 'patch_forward_experiment_lab.py') $app
  if($LASTEXITCODE -ne 0){throw 'Forward Lab API patch failed.'}

  & python (Join-Path $tmp 'patch_news_intelligence.py') $app
  if($LASTEXITCODE -ne 0){throw 'News Intelligence API patch failed.'}

  & python (Join-Path $tmp 'patch_news_research_controls.py') $app
  if($LASTEXITCODE -ne 0){throw 'News Research Controls API patch failed.'}

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'context_collector.py' 'forward_experiment_lab.py' 'news_analyzer.py' 'news_outcomes.py' 'news_research_controls.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  foreach($name in @('api.py','index.html','context_collector.py','forward_experiment_lab.py','news_analyzer.py','news_outcomes.py','news_research_controls.py')){
    $b=Join-Path $backup $name
    $dst=Join-Path $app $name
    if(Test-Path $b){Copy-Item $b $dst -Force}
    elseif($name -in @('forward_experiment_lab.py','news_analyzer.py','news_outcomes.py','news_research_controls.py')){
      Remove-Item $dst -ErrorAction SilentlyContinue
    }
  }
  throw
}
Write-Host '[OK] API patched · execution logic unchanged' -ForegroundColor Green

Write-Host '[8/14] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'docker compose rebuild failed.'}
} finally {Pop-Location}

Write-Host '[9/14] Publishing dashboard into persistent /data...'
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

Write-Host '[10/14] Checking Context RSS + Hardening + Forward Lab...'
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
Write-Host ('[OK] RSS: '+$ctx.news_sources_ok+'/'+$ctx.rss_feeds+' · cache '+$ctx.headline_cache) -ForegroundColor Green
Write-Host ('[OK] Forward Lab: '+$fwd.mode) -ForegroundColor Green
Write-Host ('[OK] Hardening: '+$hard.status) -ForegroundColor Green

Write-Host '[11/14] Running live Ollama news classification check...'
try{
  $refresh=Invoke-RestMethod 'http://127.0.0.1:8088/news-intelligence/refresh-now?limit=2' -Method Post -Headers $headers -TimeoutSec 60
  Write-Host ('News refresh: '+$refresh.status+' · analyzed '+$refresh.analyzed)
}catch{
  Write-Host ('[WARN] manual News Intelligence refresh: '+$_.Exception.Message) -ForegroundColor Yellow
}
$news=Invoke-RestMethod 'http://127.0.0.1:8088/news-intelligence/report' -Headers $headers -TimeoutSec 25
if($news.status -ne 'ok'){throw 'News Intelligence report failed.'}
Write-Host ('[OK] News analyzer: '+$news.analyzer.mode+' · Ollama '+$news.analyzer.ollama.status) -ForegroundColor Green
Write-Host ('Dynamic universe: '+(($news.analyzer.universe_assets | ForEach-Object {[string]$_}) -join ', '))
Write-Host ('Analyzed headlines: '+$news.analyzer.analysis_ok+' · errors '+$news.analyzer.analysis_error)

Write-Host '[12/14] Checking News Quality + Stories...'
$quality=Invoke-RestMethod 'http://127.0.0.1:8088/news-research/quality' -Headers $headers -TimeoutSec 15
$stories=Invoke-RestMethod 'http://127.0.0.1:8088/news-research/stories?limit=10' -Headers $headers -TimeoutSec 15
Write-Host ('News Quality: '+$quality.state+' · RSS 6h '+$quality.rss_headlines_6h)
Write-Host ('Story groups 72h: '+$stories.story_count_72h)

Write-Host '[13/14] Checking Live Readiness diagnostic...'
$ready=Invoke-RestMethod 'http://127.0.0.1:8088/live-readiness/report' -Headers $headers -TimeoutSec 20
Write-Host ('Live Readiness: '+$ready.state) -ForegroundColor $(if($ready.state -eq 'ELIGIBLE_FOR_MANUAL_REVIEW'){'Green'}else{'Yellow'})
Write-Host ('Clean STRICT: '+$ready.core_strict.n+' / required 150')
Write-Host ('STRICT Avg NET: '+([math]::Round([double]$ready.core_strict.avg_net_pct,4))+'%')
Write-Host ('STRICT PF: '+([math]::Round([double]$ready.core_strict.profit_factor,2)))
if($ready.blockers.Count -gt 0){
  Write-Host 'Readiness blockers:' -ForegroundColor Yellow
  foreach($b in $ready.blockers){Write-Host (' - '+$b.name+': '+$b.detail)}
}

Write-Host '[14/14] Opening authorized dashboard...'
$launch='http://127.0.0.1:8088/dashboard#token='+[uri]::EscapeDataString($token)
Start-Process $launch

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - RESEARCH + READINESS V4 INSTALLED ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('ASTRA health: '+$health.status)
Write-Host ('Forward Lab: '+$fwd.mode)
Write-Host ('News Quality: '+$quality.state)
Write-Host ('Story groups: '+$stories.story_count_72h)
Write-Host ('Live Readiness diagnostic: '+$ready.state)
Write-Host 'News: taxonomy + surprise + story lifecycle + source reliability + per-asset lag + impact + regime + Binance matrix'
Write-Host 'Promotion Gate: ENABLED (diagnostic only)'
Write-Host 'Live Readiness Gate: ENABLED (read-only; cannot enable LIVE)'
Write-Host 'PAPER execution changed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: '+$backup)
