$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - EDGE DIAGNOSTIC V3 ' -ForegroundColor Yellow
Write-Host ' TELEMETRY ONLY - DRY_RUN REQUIRED ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$moduleCommit='241ee7aa98f7e87be3a002ede6823a395ae692c0'
$moduleUri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$moduleCommit+'/astra_fasttrack_canary/fasttrack_paper_canary.py'
$env:COMPOSE_ANSI='never'
$env:BUILDKIT_PROGRESS='plain'

function FmtPct($v) {
  if($null -eq $v){ return 'n/a' }
  try { return ('{0:N4}%' -f [double]$v) } catch { return [string]$v }
}

$app=$null
try {
  $rawText=& docker inspect myshka-astra 2>$null
  if($LASTEXITCODE -eq 0 -and $rawText){
    $raw=$rawText | ConvertFrom-Json
    if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
      $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
    }
  }
} catch {}

if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback 'fasttrack_paper_canary.py')){$app=$fallback}
}
if(-not $app){throw 'ASTRA project folder not found.'}

$dst=Join-Path $app 'fasttrack_paper_canary.py'
if(-not (Test-Path $dst)){throw 'fasttrack_paper_canary.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=$dst+'.before-edge-diag-v3-'+$stamp
Copy-Item $dst $backup -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'myshka_fasttrack_edge_diag_v3.py'
$nonce=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()

Write-Host '[1/6] Downloading pinned EDGE diagnostic module...'
Invoke-WebRequest -UseBasicParsing -Uri ($moduleUri+'?x='+$nonce) -Headers @{
  'User-Agent'='MYSHKA-ASTRA-EdgeDiagV3'
  'Cache-Control'='no-cache, no-store, max-age=0'
  'Pragma'='no-cache'
} -OutFile $tmp -TimeoutSec 60

$src=Get-Content $tmp -Raw -Encoding UTF8
foreach($m in @('_EDGE_RECENT','edge_evaluations','edge_rejected','shadow_cache_hits','expected_move_pct','total_cost_pct','net_edge_pct')){
  if($src -notlike ('*'+$m+'*')){throw ('Missing EDGE V3 marker: '+$m)}
}

Write-Host '[2/6] Syntax check...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile $tmp
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'EDGE V3 module compile failed.'}

Write-Host '[3/6] Installing telemetry-only module...'
Copy-Item $tmp $dst -Force

Push-Location $app
try {
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & python -m py_compile 'fasttrack_paper_canary.py' 'api.py'
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){
    Copy-Item $backup $dst -Force
    throw 'Local compile failed; previous canary restored.'
  }

  Write-Host '[4/6] Rebuilding ASTRA only...'
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  & docker compose --ansi never up -d --build --force-recreate astra
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -ne 0){
    Copy-Item $backup $dst -Force
    throw 'ASTRA rebuild failed; previous canary restored.'
  }
} finally { Pop-Location }

Write-Host '[5/6] Health + DRY_RUN safety check...'
$health=$null
for($i=0;$i -lt 35;$i++){
  Start-Sleep -Seconds 2
  try {
    $health=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 6
    if($health.status -eq 'ok'){break}
  } catch {}
}
if(-not $health -or $health.status -ne 'ok'){throw 'ASTRA health failed.'}

$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' |
  Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } |
  ForEach-Object { $_.Substring($_.IndexOf('=')+1) } |
  Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

$st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
if($st.real_money_execution -ne $false){throw 'Unsafe real_money_execution flag.'}
if($st.local_dry_run -ne $true){throw 'Freqtrade DRY_RUN confirmation failed.'}
if($null -eq $st.live_funnel.edge_evaluations){throw 'EDGE V3 telemetry missing.'}

Write-Host '[OK] DRY_RUN confirmed. Real-money execution OFF.' -ForegroundColor Green

Write-Host '[6/6] Watching EDGE economics...' -ForegroundColor Cyan
Write-Host ''
Write-Host ' eval cache pass reject | pair side | ATR spread | expected cost net | basis n'
Write-Host '--------------------------------------------------------------------------------'

$lastEval=-1
for($i=0;$i -lt 40;$i++){
  $st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
  $f=$st.live_funnel
  $e=$f.last_edge

  $eval=[int]($f.edge_evaluations)
  if($eval -ne $lastEval -or $i -eq 0){
    if($null -ne $e){
      $pair=[string]$e.pair
      $side=[string]$e.side
      $basis=[string]$e.basis
      $n=[int]$e.samples
      Write-Host (('{0,4} {1,5} {2,4} {3,6} | {4} {5} | {6} {7} | {8} {9} {10} | {11} {12}' -f
        $eval,
        [int]$f.shadow_cache_hits,
        [int]$f.edge_passed,
        [int]$f.edge_rejected,
        $pair,
        $side,
        (FmtPct $e.atr_pct),
        (FmtPct $e.spread_pct),
        (FmtPct $e.expected_move_pct),
        (FmtPct $e.total_cost_pct),
        (FmtPct $e.net_edge_pct),
        $basis,
        $n))
    } else {
      Write-Host ('edge_evaluations='+$eval+' cache_hits='+[int]$f.shadow_cache_hits+' | waiting for first real EDGE evaluation')
    }
    $lastEval=$eval
  }

  if($eval -ge 12){break}
  Start-Sleep -Seconds 15
}

$st=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
$f=$st.live_funnel

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' EDGE DIAGNOSTIC V3 READY ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Real EDGE evaluations: '+$f.edge_evaluations)
Write-Host ('Shadow cache hits:      '+$f.shadow_cache_hits)
Write-Host ('EDGE passed:            '+$f.edge_passed)
Write-Host ('EDGE rejected:          '+$f.edge_rejected)
Write-Host ('Repeated reject counter: '+$f.jev_shadow_edge_reject)
Write-Host ''
Write-Host 'Important: edge_evaluations is the real calculation count.'
Write-Host 'jev_shadow_edge_reject may be much larger because cached rejects are counted again by the funnel.'
Write-Host 'Trading thresholds changed: NO'
Write-Host 'JEV decision rules changed: NO'
Write-Host 'Freqtrade DRY_RUN changed: NO'
Write-Host 'Real-money execution: OFF'
Write-Host ('Backup: '+$backup)
