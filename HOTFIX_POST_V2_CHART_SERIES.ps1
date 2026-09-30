$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - POST-V2 CHART SERIES HOTFIX ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$bundleCommit = '75b2603dee3968147368df1f4591f8fb0048d2de'
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
if (-not $app -or -not (Test-Path (Join-Path $app 'api.py'))) {
  throw 'ASTRA project folder not found.'
}
Write-Host ('[OK] ASTRA project: ' + $app) -ForegroundColor Green

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$backup = Join-Path $app ('backup-before-post-v2-chart-series-' + $stamp)
New-Item -ItemType Directory -Path $backup -Force | Out-Null
$dst = Join-Path $app 'multihorizon_shadow.py'
if(Test-Path $dst){ Copy-Item $dst (Join-Path $backup 'multihorizon_shadow.py') -Force }

$tmp = Join-Path $env:TEMP 'myshka_post_v2_chart_series'
if(Test-Path $tmp){ Remove-Item $tmp -Recurse -Force }
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

Write-Host '[1/5] Downloading updated Multi-Horizon module...'
Invoke-WebRequest -UseBasicParsing -Uri ($root + '/astra_multihorizon_shadow/multihorizon_shadow.py') -OutFile (Join-Path $tmp 'multihorizon_shadow.py')

Write-Host '[2/5] Syntax check...'
& python -m py_compile (Join-Path $tmp 'multihorizon_shadow.py')
if($LASTEXITCODE -ne 0){ throw 'Python syntax failed. Local ASTRA not modified.' }

Write-Host '[3/5] Installing module...'
Copy-Item (Join-Path $tmp 'multihorizon_shadow.py') $dst -Force
Push-Location $app
try {
  & python -m py_compile 'api.py' 'multihorizon_shadow.py'
  if($LASTEXITCODE -ne 0){
    if(Test-Path (Join-Path $backup 'multihorizon_shadow.py')){
      Copy-Item (Join-Path $backup 'multihorizon_shadow.py') $dst -Force
    }
    throw 'Final compile failed; previous module restored.'
  }
} finally { Pop-Location }

Write-Host '[4/5] Rebuilding ASTRA...'
Push-Location $app
try {
  docker compose up -d --build --force-recreate astra
  if($LASTEXITCODE -ne 0){ throw 'docker compose rebuild failed.' }
} finally { Pop-Location }

Write-Host '[5/5] Checking POST-V2 chart series endpoint...'
$health = $null
for($i=0; $i -lt 45; $i++){
  Start-Sleep -Seconds 2
  try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($health.status -eq 'ok'){ break }
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){ throw 'ASTRA health failed after chart-series hotfix.' }

$token = (docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $token){ throw 'MYSHKA_BRIDGE_TOKEN not found.' }

$report = Invoke-RestMethod 'http://127.0.0.1:8088/post-calibration/report' -Headers @{'X-MYSHKA-TOKEN'=$token} -TimeoutSec 10
if(-not $report.chart_series){ throw 'POST-V2 report does not contain chart_series.' }

Write-Host ''
Write-Host '==============================================' -ForegroundColor Green
Write-Host ' READY - POST-V2 CHART SERIES HOTFIX ' -ForegroundColor Green
Write-Host '==============================================' -ForegroundColor Green
Write-Host ('ASTRA health: ' + $health.status)
Write-Host ('5m points: ' + @($report.chart_series.'300').Count)
Write-Host ('10m points: ' + @($report.chart_series.'600').Count)
Write-Host ('15m points: ' + @($report.chart_series.'900').Count)
Write-Host 'LIVE routing added: NO'
Write-Host ('Backup: ' + $backup)
