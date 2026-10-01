$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '======================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FASTTRACK TRIPLE INTERSECTION ' -ForegroundColor Yellow
Write-Host ' TECH 3/4 + JEV APPROVE + BINANCE AGREE ' -ForegroundColor Yellow
Write-Host '======================================================' -ForegroundColor Cyan

$commit='d073409201809e42057b0fde1039b9daf4f5340c'
$uri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$commit+'/astra_fasttrack/fasttrack_triple_intersection.py'
$tmp=Join-Path $env:TEMP 'myshka_fasttrack_triple_intersection.py'

Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $tmp -TimeoutSec 60

$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile $tmp
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'Analyzer syntax invalid.'}

Write-Host '[1/2] Running read-only JOIN inside ASTRA container...'
Get-Content $tmp -Raw | docker exec -i myshka-astra python - > (Join-Path $env:TEMP 'myshka_fasttrack_result.json')
if($LASTEXITCODE -ne 0){throw 'Fasttrack analysis failed.'}

$resultPath=Join-Path $env:TEMP 'myshka_fasttrack_result.json'
$raw=Get-Content $resultPath -Raw
$r=$raw | ConvertFrom-Json

Write-Host '[2/2] Result...' -ForegroundColor Green
Write-Host ''
Write-Host ('Joined rows: '+$r.joined_rows)
Write-Host ('JEV distribution: '+($r.jev_distribution | ConvertTo-Json -Compress))

Write-Host ''
Write-Host '=== FASTTRACK FUNNEL ===' -ForegroundColor Cyan
foreach($name in @('TECH3','TECH3_JEV_APPROVE','TECH3_BINANCE_AGREE','TRIPLE','STRICT4')){
  $node=$r.funnel.$name
  if($node){
    $m=$node.'300'
    Write-Host ($name+' | 5m cn='+$m.cluster_n+
      ' | Avg NET='+([math]::Round([double]$m.cluster_avg_net_pct,4))+'%'+
      ' | PF='+([math]::Round([double]$m.cluster_profit_factor,2))+
      ' | Win='+([math]::Round([double]$m.cluster_win_rate_pct,1))+'%')
  }
}

Write-Host ''
Write-Host ('PAPER CANARY ELIGIBLE: '+$r.paper_canary_eligible) -ForegroundColor Yellow
Write-Host ('Reason: '+$r.paper_canary_reason)
foreach($h in @('300','600','900')){
  $m=$r.by_horizon.$h
  if($m){
    $label=if($h -eq '300'){'5m'}elseif($h -eq '600'){'10m'}else{'15m'}
    Write-Host ('['+$label+'] raw n='+$m.n+' | cluster n='+$m.cluster_n+
      ' | Avg NET='+([math]::Round([double]$m.cluster_avg_net_pct,4))+'%'+
      ' | Median='+([math]::Round([double]$m.cluster_median_net_pct,4))+'%'+
      ' | PF='+([math]::Round([double]$m.cluster_profit_factor,2))+
      ' | Win='+([math]::Round([double]$m.cluster_win_rate_pct,1))+'%')
  }
}

Write-Host ''
Write-Host '5m pair breakdown:' -ForegroundColor Cyan
$r.pair_breakdown_5m.PSObject.Properties | ForEach-Object {
  $m=$_.Value
  Write-Host (' '+$_.Name+' | cn='+$m.cluster_n+
    ' | Avg NET='+([math]::Round([double]$m.cluster_avg_net_pct,4))+'%'+
    ' | PF='+([math]::Round([double]$m.cluster_profit_factor,2)))
}

Write-Host ''
Write-Host '5m side breakdown:' -ForegroundColor Cyan
$r.side_breakdown_5m.PSObject.Properties | ForEach-Object {
  $m=$_.Value
  Write-Host (' '+$_.Name+' | cn='+$m.cluster_n+
    ' | Avg NET='+([math]::Round([double]$m.cluster_avg_net_pct,4))+'%'+
    ' | PF='+([math]::Round([double]$m.cluster_profit_factor,2)))
}

Write-Host ''
Write-Host '5m regime breakdown:' -ForegroundColor Cyan
$r.regime_breakdown_5m.PSObject.Properties | ForEach-Object {
  $m=$_.Value
  Write-Host (' '+$_.Name+' | cn='+$m.cluster_n+
    ' | Avg NET='+([math]::Round([double]$m.cluster_avg_net_pct,4))+'%'+
    ' | PF='+([math]::Round([double]$m.cluster_profit_factor,2)))
}

Write-Host ''
Write-Host ('Full JSON: '+$resultPath)
Write-Host 'Read-only diagnostic: no trading decisions changed, no orders sent.' -ForegroundColor DarkGray
