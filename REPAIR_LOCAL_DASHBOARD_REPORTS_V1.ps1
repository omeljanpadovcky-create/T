$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - REPAIR LOCAL DASHBOARD REPORTS V1 ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$commit='5d53d9e4b924d107cf30a0377a717f355d6701b7'
$url='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$commit+'/index.html'
$tmp=Join-Path $env:TEMP 'myshka_dashboard_reports_v1.html'

Write-Host '[1/5] Downloading repaired dashboard...'
Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $tmp
$html=Get-Content $tmp -Raw
foreach($m in @('refreshSecondaryReports','localAstraOrigin','POSTV2_300','binanceCrosscheckPanel')){
  if($html -notlike ('*'+$m+'*')){ throw ('Downloaded dashboard missing marker: '+$m) }
}
Write-Host '[OK] dashboard markers valid' -ForegroundColor Green

Write-Host '[2/5] Copying dashboard into ASTRA /data...'
docker cp $tmp 'myshka-astra:/data/myshka_dashboard.html'
if($LASTEXITCODE -ne 0){ throw 'docker cp failed' }
Write-Host '[OK] dashboard updated' -ForegroundColor Green

Write-Host '[3/5] Reading bridge token...'
$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  Select-Object -First 1) -replace '^MYSHKA_BRIDGE_TOKEN=',''
if(-not $token){ throw 'MYSHKA_BRIDGE_TOKEN not found' }
$headers=@{'X-MYSHKA-TOKEN'=$token}

Write-Host '[4/5] Checking report endpoints one by one...'
$checks=@(
  '/post-calibration/report',
  '/binance-crosscheck/report',
  '/analytics/report?mode=STRICT&min_segment_n=3',
  '/counterfactual/report?min_stage_n=3',
  '/risk-intelligence/report',
  '/risk-intelligence/quality',
  '/risk-intelligence/replay?limit=1',
  '/hardening/status'
)
$bad=@()
foreach($p in $checks){
  try{
    $r=Invoke-RestMethod ('http://127.0.0.1:8088'+$p) -Headers $headers -TimeoutSec 30
    $status=[string]$r.status
    if(-not $status){$status='ok'}
    Write-Host ('[OK] '+$p+' -> '+$status) -ForegroundColor Green
  }catch{
    $bad += $p
    Write-Host ('[WARN] '+$p+' -> '+$_.Exception.Message) -ForegroundColor Yellow
  }
}

Write-Host '[5/5] Opening authorized local dashboard...'
$launch='http://127.0.0.1:8088/dashboard#token='+[uri]::EscapeDataString($token)
Start-Process $launch

Write-Host ''
Write-Host '======================================================' -ForegroundColor Green
Write-Host ' DASHBOARD REPAIR APPLIED ' -ForegroundColor Green
Write-Host '======================================================' -ForegroundColor Green
Write-Host 'Core UI timeout: 6.5s'
Write-Host 'Heavy reports: 12-22s'
Write-Host 'Heavy refresh cadence: 30s, non-overlapping'
Write-Host 'Archive mode aliases: expanded'
Write-Host 'Trading logic changed: NO'
Write-Host 'LIVE routing added: NO'
if($bad.Count){
  Write-Host ('Backend endpoints still warning: '+($bad -join ', ')) -ForegroundColor Yellow
}else{
  Write-Host 'All report endpoints: OK' -ForegroundColor Green
}
