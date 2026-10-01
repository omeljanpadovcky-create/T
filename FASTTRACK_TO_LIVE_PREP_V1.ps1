$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - FASTTRACK TO LIVE PREP V1 ' -ForegroundColor Yellow
Write-Host ' EXECUTION AUDIT + DATA FUNNEL + CANARY GATE ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ''
Write-Host 'This package does NOT arm LIVE.' -ForegroundColor Yellow
Write-Host 'It prepares execution telemetry and evaluates the fastest evidence path.' -ForegroundColor Yellow
Write-Host ''

$work=Join-Path $env:TEMP 'myshka_fasttrack_to_live_prep_v1'
if(Test-Path $work){Remove-Item $work -Recurse -Force}
New-Item -ItemType Directory -Path $work -Force | Out-Null

$auditCommit='214719b6d4fe2c662d7db5ab85376f203e5808f4'
$analysisCommit='73dbbb4bf549dc3901341a7504aa45c7bc8ad156'

$auditUri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$auditCommit+'/INSTALL_EXECUTION_SLIPPAGE_AUDIT_V1.ps1'
$analysisUri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$analysisCommit+'/RUN_FASTTRACK_TRIPLE_ANALYSIS.ps1'

$auditScript=Join-Path $work 'INSTALL_EXECUTION_SLIPPAGE_AUDIT_V1.ps1'
$analysisScript=Join-Path $work 'RUN_FASTTRACK_TRIPLE_ANALYSIS.ps1'

Write-Host '[1/4] Downloading pinned fast-track tools...'
Invoke-WebRequest -UseBasicParsing -Uri $auditUri -OutFile $auditScript -TimeoutSec 60
Invoke-WebRequest -UseBasicParsing -Uri $analysisUri -OutFile $analysisScript -TimeoutSec 60
Write-Host '[OK] Tools downloaded.' -ForegroundColor Green

Write-Host '[2/4] Installing execution slippage audit...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& powershell -ExecutionPolicy Bypass -File $auditScript
$auditRc=$LASTEXITCODE
$ErrorActionPreference=$old
if($auditRc -ne 0){throw ('Execution audit installer failed with code '+$auditRc)}
Write-Host '[OK] Execution audit installed.' -ForegroundColor Green

Write-Host '[3/4] Running fast-track data funnel...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& powershell -ExecutionPolicy Bypass -File $analysisScript
$analysisRc=$LASTEXITCODE
$ErrorActionPreference=$old
if($analysisRc -ne 0){throw ('Fast-track analysis failed with code '+$analysisRc)}
Write-Host '[OK] Fast-track analysis completed.' -ForegroundColor Green

$resultPath=Join-Path $env:TEMP 'myshka_fasttrack_result.json'
if(-not (Test-Path $resultPath)){throw 'Fast-track result JSON not found.'}
$r=Get-Content $resultPath -Raw | ConvertFrom-Json

Write-Host '[4/4] Final gate...' -ForegroundColor Cyan
Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' FASTTRACK PREP COMPLETE ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Joined rows: '+$r.joined_rows)
Write-Host ('JEV distribution: '+($r.jev_distribution | ConvertTo-Json -Compress))
Write-Host ('PAPER CANARY ELIGIBLE: '+$r.paper_canary_eligible) -ForegroundColor Yellow
Write-Host ('Reason: '+$r.paper_canary_reason)
Write-Host ''

$tri=$r.funnel.TRIPLE
if($tri){
  foreach($h in @('300','600','900')){
    $m=$tri.$h
    $label=if($h -eq '300'){'5m'}elseif($h -eq '600'){'10m'}else{'15m'}
    Write-Host ('TRIPLE '+$label+
      ' | cn='+$m.cluster_n+
      ' | Avg NET='+([math]::Round([double]$m.cluster_avg_net_pct,4))+'%'+
      ' | PF='+([math]::Round([double]$m.cluster_profit_factor,2))+
      ' | Win='+([math]::Round([double]$m.cluster_win_rate_pct,1))+'%')
  }
}

Write-Host ''
Write-Host 'Execution telemetry:' -ForegroundColor Cyan
Write-Host ' - Freqtrade slippage audit installed'
Write-Host ' - signal price vs open_rate'
Write-Host ' - engine latency + fill-observed latency'
Write-Host ' - Telegram alert >= 20 bps'
Write-Host ' - DRY_RUN fills marked simulated'
Write-Host ' - LIVE bridge telemetry preinstalled'
Write-Host ''
Write-Host 'Safety state:' -ForegroundColor Cyan
Write-Host ' - LIVE armed: NO'
Write-Host ' - Freqtrade dry_run changed: NO'
Write-Host ' - Trading decisions changed: NO'
Write-Host ''
Write-Host ('Full analysis JSON: '+$resultPath)
