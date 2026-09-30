$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - INSTALL RESCUE MATRIX V1 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit='852e6684e460e6d9e48c744fb1320e2a52c7fa4c'
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

Write-Host '[0/9] Preflight current api.py...'
& python -m py_compile (Join-Path $app 'api.py')
if($LASTEXITCODE -ne 0){throw 'Current api.py is invalid. Nothing modified.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=Join-Path $app ('backup-before-rescue-matrix-v1-'+$stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($name in @('api.py','index.html','rescue_matrix.py')){
  $src=Join-Path $app $name
  if(Test-Path $src){Copy-Item $src (Join-Path $backup $name) -Force}
}
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_rescue_matrix_v1'
if(Test-Path $tmp){Remove-Item $tmp -Recurse -Force}
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/9] Downloading RESCUE MATRIX bundle...'
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_rescue_matrix/rescue_matrix.py') -OutFile (Join-Path $tmp 'rescue_matrix.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_rescue_matrix/patch_rescue_matrix.py') -OutFile (Join-Path $tmp 'patch_rescue_matrix.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/astra_rescue_matrix/selftest_rescue_matrix.py') -OutFile (Join-Path $tmp 'selftest_rescue_matrix.py')
Invoke-WebRequest -UseBasicParsing -Uri ($root+'/index.html') -OutFile (Join-Path $tmp 'index.html')

Write-Host '[2/9] Compile + dashboard checks...'
& python -m py_compile (Join-Path $tmp 'rescue_matrix.py') (Join-Path $tmp 'patch_rescue_matrix.py') (Join-Path $tmp 'selftest_rescue_matrix.py')
if($LASTEXITCODE -ne 0){throw 'RESCUE MATRIX Python compile failed. Local ASTRA not modified.'}
$html=Get-Content (Join-Path $tmp 'index.html') -Raw
foreach($m in @('RESCUE MATRIX · SHADOW','refreshRescueMatrix','/rescue-matrix/report','Forward confirmation')){
  if($html -notlike ('*'+$m+'*')){throw ('Dashboard missing marker: '+$m)}
}
Write-Host '[OK] code + dashboard markers valid' -ForegroundColor Green

Write-Host '[3/9] Synthetic RESCUE MATRIX self-test...'
$pkg=Join-Path $tmp 'rescuepkg'
New-Item -ItemType Directory -Path $pkg -Force | Out-Null
New-Item -ItemType File -Path (Join-Path $pkg '__init__.py') -Force | Out-Null
Copy-Item (Join-Path $tmp 'rescue_matrix.py') (Join-Path $pkg 'rescue_matrix.py') -Force
Copy-Item (Join-Path $tmp 'selftest_rescue_matrix.py') (Join-Path $pkg 'selftest_rescue_matrix.py') -Force
Push-Location $tmp
try {
  & python -m rescuepkg.selftest_rescue_matrix
  if($LASTEXITCODE -ne 0){throw 'RESCUE MATRIX self-test failed. Local ASTRA not modified.'}
} finally {Pop-Location}
Write-Host '[OK] RESCUE MATRIX self-test passed' -ForegroundColor Green

Write-Host '[4/9] Installing module + dashboard...'
Copy-Item (Join-Path $tmp 'rescue_matrix.py') (Join-Path $app 'rescue_matrix.py') -Force
Copy-Item (Join-Path $tmp 'index.html') (Join-Path $app 'index.html') -Force

Write-Host '[5/9] Patching API...'
try {
  & python (Join-Path $tmp 'patch_rescue_matrix.py') $app
  if($LASTEXITCODE -ne 0){throw 'RESCUE MATRIX API patch failed.'}

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'rescue_matrix.py'
    if($LASTEXITCODE -ne 0){throw 'Patched ASTRA compile failed.'}
  } finally {Pop-Location}
} catch {
  if(Test-Path (Join-Path $backup 'api.py')){Copy-Item (Join-Path $backup 'api.py') (Join-Path $app 'api.py') -Force}
  if(Test-Path (Join-Path $backup 'index.html')){Copy-Item (Join-Path $backup 'index.html') (Join-Path $app 'index.html') -Force}
  if(Test-Path (Join-Path $backup 'rescue_matrix.py')){
    Copy-Item (Join-Path $backup 'rescue_matrix.py') (Join-Path $app 'rescue_matrix.py') -Force
  }else{
    Remove-Item (Join-Path $app 'rescue_matrix.py') -ErrorAction SilentlyContinue
  }
  throw
}
Write-Host '[OK] API patched · no observer added · trading logic unchanged' -ForegroundColor Green

Write-Host '[6/9] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){throw 'docker compose rebuild failed.'}
} finally {Pop-Location}

Write-Host '[7/9] Publishing dashboard + waiting for health...'
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

Write-Host '[8/9] Checking RESCUE MATRIX against real ASTRA DB...'
$report=Invoke-RestMethod 'http://127.0.0.1:8088/rescue-matrix/report' -Headers $headers -TimeoutSec 30
$risk=Invoke-RestMethod 'http://127.0.0.1:8088/risk-intelligence/report' -Headers $headers -TimeoutSec 20
$hard=Invoke-RestMethod 'http://127.0.0.1:8088/hardening/status' -Headers $headers -TimeoutSec 10
if($report.status -ne 'ok'){throw 'RESCUE MATRIX report failed.'}
if($risk.status -ne 'ok'){throw 'Risk Intelligence regression detected.'}
if($hard.status -ne 'ok'){throw 'Hardening regression detected.'}

$hist=$report.historical
$fwd=$report.forward
$discoveries=@($hist.matrix.top_positive_intersections).Count
$reviews=@($fwd.matrix.top_positive_intersections | Where-Object { $_.forward_review_eligible -eq $true }).Count
Write-Host ('[OK] Historical raw: '+$hist.overall.n+' · cn '+$hist.overall.cluster_n) -ForegroundColor Green
Write-Host ('[OK] Black Box join: '+([math]::Round([double]$hist.blackbox_join_coverage_pct,1))+'%') -ForegroundColor Green
Write-Host ('[OK] Historical discovery pockets: '+$discoveries) -ForegroundColor Green
Write-Host ('[OK] Forward cn: '+$fwd.overall.cluster_n+' · review eligible '+$reviews) -ForegroundColor Green
Write-Host ('[OK] Risk Intelligence: '+$risk.sample_state) -ForegroundColor Green
Write-Host ('[OK] Hardening: '+$hard.status) -ForegroundColor Green

if($discoveries -gt 0){
  Write-Host ''
  Write-Host 'Top historical DISCOVERY pockets:' -ForegroundColor Cyan
  $i=0
  foreach($x in @($hist.matrix.top_positive_intersections)){
    if($i -ge 5){break}
    $parts=@()
    foreach($k in @('tech','edge_band','regime','pair','xcheck','evidence')){
      if($x.values.PSObject.Properties.Name -contains $k){$parts+=($k+'='+$x.values.$k)}
    }
    Write-Host (' - '+($parts -join ' | ')+' | cn='+$x.cluster_n+' | avg='+([math]::Round([double]$x.cluster_avg_net_pct,3))+'% | PF='+([math]::Round([double]$x.cluster_profit_factor,2))+' | DISCOVERY ONLY')
    $i++
  }
}

Write-Host '[9/9] Opening authorized dashboard...'
$launch='http://127.0.0.1:8088/dashboard#token='+[uri]::EscapeDataString($token)
Start-Process $launch

Write-Host ''
Write-Host '======================================================' -ForegroundColor Green
Write-Host ' READY - RESCUE MATRIX V1 INSTALLED ' -ForegroundColor Green
Write-Host '======================================================' -ForegroundColor Green
Write-Host ('ASTRA health: '+$health.status)
Write-Host ('Historical clusters: '+$hist.overall.cluster_n)
Write-Host ('Historical discovery pockets: '+$discoveries)
Write-Host ('Forward clusters: '+$fwd.overall.cluster_n)
Write-Host ('Forward review eligible: '+$reviews)
Write-Host 'Historical findings: DISCOVERY ONLY'
Write-Host 'Forward review threshold: 150 clusters + positive Avg NET + PF >= 1.20'
Write-Host 'PAPER execution changed: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: '+$backup)
