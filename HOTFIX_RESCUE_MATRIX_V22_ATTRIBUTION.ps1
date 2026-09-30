$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - RESCUE MATRIX V2.2 ATTRIBUTION HOTFIX ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$bundleCommit='05c3c60f37c90f4801566577f586ecf3be211007'
$rawRoot='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$bundleCommit

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

$dst=Join-Path $app 'rescue_matrix.py'
if(-not (Test-Path $dst)){throw 'rescue_matrix.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('rescue_matrix.py.backup-v22-attribution-'+$stamp)
Copy-Item $dst $backup -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_rescue_v22_attribution.py'
$nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()
$uri=$rawRoot+'/astra_rescue_matrix/rescue_matrix.py?x='+$nonce

Write-Host '[1/7] Downloading V2.2 attribution module...'
Invoke-WebRequest -UseBasicParsing -Uri $uri -Headers @{
  'User-Agent'='MYSHKA-ASTRA-Hotfix'
  'Cache-Control'='no-cache, no-store, max-age=0'
  'Pragma'='no-cache'
} -OutFile $tmp -TimeoutSec 60

Write-Host '[2/7] Verifying markers...'
$src=Get-Content $tmp -Raw -Encoding UTF8
foreach($m in @(
  'BINARY_JOIN_CACHE_ATTRIBUTION_V2_2',
  'attribution_funnel',
  'blackbox_column',
  'jev_verdict',
  'JEV_APPROVE_x_TECH_3_OF_4'
)){
  if($src -notlike ('*'+$m+'*')){throw ('Missing V2.2 marker: '+$m)}
}
$initStart=$src.IndexOf('def init() -> dict:')
$nextDef=$src.IndexOf('def _num',$initStart)
if($initStart -lt 0 -or $nextDef -le $initStart){throw 'Cannot verify init() block.'}
$initBlock=$src.Substring($initStart,$nextDef-$initStart)
if($initBlock -match 'return\s+status\s*\(\s*\)'){throw 'Recursion regression detected.'}

Write-Host '[3/7] Python compile...'
& python -m py_compile $tmp
if($LASTEXITCODE -ne 0){throw 'V2.2 compile failed. ASTRA unchanged.'}

Write-Host '[4/7] Installing module...'
Copy-Item $tmp $dst -Force

Push-Location $app
try {
  & python -m py_compile 'api.py' 'rescue_matrix.py'
  if($LASTEXITCODE -ne 0){
    Copy-Item $backup $dst -Force
    throw 'Local compile failed. Previous module restored.'
  }

  Write-Host '[5/7] Rebuilding ASTRA...'
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){
    Copy-Item $backup $dst -Force
    docker compose up -d --build --force-recreate astra | Out-Null
    throw 'Rebuild failed. Previous module restored.'
  }
} finally {Pop-Location}

Write-Host '[6/7] Health check...'
$health=$null
for($i=0;$i -lt 45;$i++){
  Start-Sleep -Seconds 2
  try{
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){break}
  }catch{}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed.'}

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

Write-Host '[7/7] Benchmark + attribution funnel...'
$sw=[Diagnostics.Stopwatch]::StartNew()
$rescue=Invoke-RestMethod 'http://127.0.0.1:8088/rescue-matrix/report' -Headers $headers -TimeoutSec 90
$sw.Stop()

if($rescue.status -ne 'ok'){throw 'Rescue report returned non-ok.'}
if($rescue.performance_mode -ne 'BINARY_JOIN_CACHE_ATTRIBUTION_V2_2'){throw ('Unexpected mode: '+$rescue.performance_mode)}
if($rescue.changes_paper_execution -ne $false){throw 'PAPER safety invariant failed.'}
if($rescue.changes_trading_decisions -ne $false){throw 'Decision safety invariant failed.'}
if($rescue.live_execution -ne $false){throw 'LIVE safety invariant failed.'}

$h5=$rescue.by_horizon.'300'
$f=$null
if($h5){$f=$h5.rescue.attribution_funnel}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - RESCUE MATRIX V2.2 ATTRIBUTION ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Report time: '+[math]::Round($sw.Elapsed.TotalSeconds,2)+' sec')
Write-Host ('Performance mode: '+$rescue.performance_mode)
Write-Host ('Risk join: '+[math]::Round([double]$rescue.coverage.risk_join_pct,1)+'%')
Write-Host ('Blackbox join: '+[math]::Round([double]$rescue.coverage.blackbox_join_pct,1)+'%')
if($f){
  Write-Host ('5m ALL raw: '+$f.all_raw_n)
  Write-Host ('5m JEV APPROVE raw: '+$f.jev_approve_raw_n)
  Write-Host ('5m TECH 3/4 raw: '+$f.tech3_raw_n)
  Write-Host ('5m JEV APPROVE x TECH 3/4 raw: '+$f.jev_approve_x_tech3_raw_n)
  Write-Host ('JEV source distribution: '+($f.jev_source_distribution | ConvertTo-Json -Compress))
  Write-Host ('JEV distribution: '+($f.jev_distribution | ConvertTo-Json -Compress))
  Write-Host ('TECH distribution: '+($f.tech_distribution | ConvertTo-Json -Compress))
}
if($h5){
  $a=$h5.rescue.anchor_metrics
  Write-Host ('Anchor raw '+$a.raw_n+' / cn '+$a.cn+' · Avg NET '+[math]::Round([double]$a.avg_net_pct,4)+'% · PF '+[math]::Round([double]$a.profit_factor,2))
  Write-Host ('Positive pockets: '+$h5.rescue.top_positive_clusters.Count)
  Write-Host ('Toxic pockets: '+$h5.rescue.top_toxic_clusters.Count)
}
Write-Host 'PAPER execution changed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: '+$backup)
