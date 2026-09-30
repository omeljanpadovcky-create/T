$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - POST-CALIBRATION V2 DASHBOARD ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '83f4310e269e9bc97caaf2fa2f634d40bee94f44'
$root = 'https://raw.githubusercontent.com/omeljanpadovcky-create/T/' + $bundleCommit

$app = $null
try {
  $raw = docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if ($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir') {
    $app = $raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
} catch {}
if (-not $app) {
  $fallback = Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if (Test-Path (Join-Path $fallback 'api.py')) { $app = $fallback }
}
if (-not $app -or -not (Test-Path (Join-Path $app 'api.py'))) { throw 'ASTRA project folder not found.' }
Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-post-calibration-dashboard-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
foreach($f in @('api.py','multihorizon_shadow.py')) {
  $src = Join-Path $app $f
  if(Test-Path $src){ Copy-Item $src (Join-Path $backup $f) -Force }
}
Write-Host ('[OK] Backup: ' + $backup) -ForegroundColor Green

$tmp = Join-Path $env:TEMP 'myshka_post_calibration_dashboard_v1'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

$downloads = @{
  'multihorizon_shadow.py' = $root + '/astra_multihorizon_shadow/multihorizon_shadow.py'
  'selftest_multihorizon_shadow.py' = $root + '/astra_multihorizon_shadow/selftest_multihorizon_shadow.py'
  'patch_post_calibration_dashboard.py' = $root + '/astra_edge_calibration_v2/patch_post_calibration_dashboard.py'
}

Write-Host '[1/7] Downloading pinned POST-V2 bundle...'
foreach($name in $downloads.Keys){
  Invoke-WebRequest -UseBasicParsing -Uri $downloads[$name] -OutFile (Join-Path $tmp $name)
}
Write-Host '[OK] Bundle downloaded.' -ForegroundColor Green

Write-Host '[2/7] Syntax check...'
foreach($name in $downloads.Keys){
  Write-Host ('  compile: ' + $name)
  & python -m py_compile (Join-Path $tmp $name)
  if($LASTEXITCODE -ne 0){ throw ('Python syntax invalid in ' + $name + '. Local ASTRA not modified.') }
}
Write-Host '[OK] Python syntax valid.' -ForegroundColor Green

Write-Host '[3/7] Running isolated POST-V2 self-test...'
Push-Location $tmp
try {
  & python '.\selftest_multihorizon_shadow.py'
  if($LASTEXITCODE -ne 0){ throw 'POST-V2/Multi-Horizon self-test failed. Local ASTRA not modified.' }
} finally { Pop-Location }
Write-Host '[OK] POST-V2 self-test passed.' -ForegroundColor Green

Write-Host '[4/7] Installing backend report...'
try {
  Copy-Item (Join-Path $tmp 'multihorizon_shadow.py') (Join-Path $app 'multihorizon_shadow.py') -Force
  & python (Join-Path $tmp 'patch_post_calibration_dashboard.py') $app
  if($LASTEXITCODE -ne 0){ throw 'POST-V2 API patch failed.' }

  Push-Location $app
  try {
    & python -m py_compile 'api.py' 'multihorizon_shadow.py'
    if($LASTEXITCODE -ne 0){ throw 'Final project compile failed.' }
  } finally { Pop-Location }
} catch {
  foreach($f in @('api.py','multihorizon_shadow.py')){
    $old = Join-Path $backup $f
    if(Test-Path $old){ Copy-Item $old (Join-Path $app $f) -Force }
  }
  Write-Host '[ROLLBACK] Restored pre-dashboard backend files.' -ForegroundColor Yellow
  throw
}
Write-Host '[OK] Backend report installed.' -ForegroundColor Green

Write-Host '[5/7] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[6/7] Waiting for ASTRA + POST-V2 endpoint...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 4
    if($health.status -eq 'ok' -and $health.multihorizon_shadow){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health check failed.' }

$token = $null

# Prefer the exact Bridge token actually used by ASTRA (_require_token -> CONFIG.BRIDGE_TOKEN).
try {
  $containerEnv = docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' 2>$null
  $tokenLine = $containerEnv | Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } | Select-Object -First 1
  if($tokenLine){
    $token = ($tokenLine -split '=',2)[1]
  }
} catch {}

# Fallback to project .env only if the running container did not expose it.
if(-not $token){
  $envFile = Join-Path $app '.env'
  if(Test-Path $envFile){
    $line = Get-Content $envFile | Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } | Select-Object -First 1
    if($line){ $token = ($line -replace '^MYSHKA_BRIDGE_TOKEN=','').Trim().Trim('"').Trim("'") }
  }
}

# Last fallback: current PowerShell environment.
if(-not $token){ $token = $env:MYSHKA_BRIDGE_TOKEN }

$headers = @{}
if($token){ $headers['X-MYSHKA-TOKEN'] = $token }

$post = $null
try {
  $post = Invoke-RestMethod 'http://127.0.0.1:8088/post-calibration/report' -Headers $headers -TimeoutSec 15
} catch {
  throw ('POST-V2 endpoint check failed: ' + $_.Exception.Message)
}
if(-not $post -or $post.status -ne 'ok'){ throw 'POST-V2 endpoint returned invalid response.' }

Write-Host '[7/7] Summary...'
Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - POST-CALIBRATION V2 DASHBOARD ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('POST-V2 state: ' + $post.sample_state)
Write-Host ('POST-V2 started_at: ' + ([DateTimeOffset]::FromUnixTimeSeconds([int64]$post.started_at).ToLocalTime().ToString('yyyy-MM-dd HH:mm:ss')))
Write-Host ('POST-V2 PAPER trades: ' + $post.paper_strict.n)
Write-Host ('POST-V2 Win rate: ' + ([math]::Round([double]$post.paper_strict.net_win_rate_pct,1)) + '%')
Write-Host ('POST-V2 Avg NET: ' + ([math]::Round([double]$post.paper_strict.avg_net_pct,3)) + '%')
Write-Host ('POST-V2 PF: ' + ([math]::Round([double]$post.paper_strict.profit_factor,2)))
Write-Host ('Multi-Horizon: ' + ($post.horizons_sec -join ',') + ' sec')
Write-Host ''
Write-Host 'Dashboard UI is already updated on GitHub Pages.'
Write-Host 'Refresh the browser with Ctrl+F5 after this installer finishes.'
Write-Host ''
Write-Host 'Trading decisions changed: NO'
Write-Host 'LIVE routing added: NO'
Write-Host 'Extra market API calls: NO'
Write-Host ('Backup: ' + $backup)
