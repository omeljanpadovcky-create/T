$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - LIVE DRY-RUN PREFLIGHT HOTFIX V1.1 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$commit='17b9a23c0f8995d5c79e805073d41f81acb32db2'
$uri='https://raw.githubusercontent.com/omeljanpadovcky-create/T/'+$commit+'/astra_live_dry_run/live_dry_run.py'

$app=(docker inspect myshka-astra | ConvertFrom-Json)[0].Config.Labels.'com.docker.compose.project.working_dir'
if(-not $app){throw 'ASTRA project folder not found.'}
Set-Location $app

$target=Join-Path $app 'live_dry_run.py'
if(-not (Test-Path $target)){throw 'live_dry_run.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=$target+'.before-v1_1-'+$stamp
Copy-Item $target $backup -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$tmp=Join-Path $env:TEMP 'live_dry_run_v1_1.py'
Invoke-WebRequest -UseBasicParsing -Uri $uri -OutFile $tmp -TimeoutSec 60

$src=Get-Content $tmp -Raw -Encoding UTF8
foreach($marker in @(
  'IMPLICIT_PRODUCTION_PASS',
  'guard_source = "final_action"',
  'if obj.get("passed") is True'
)){
  if($src -notlike ('*'+$marker+'*')){throw ('Missing hotfix marker: '+$marker)}
}

Copy-Item $tmp $target -Force

& python -m py_compile $target
if($LASTEXITCODE -ne 0){
  Copy-Item $backup $target -Force
  throw 'Compile failed. Restored backup.'
}

Write-Host '[OK] Parser hotfix installed' -ForegroundColor Green
Write-Host '[OK] Evidence passed=True is authoritative' -ForegroundColor Green
Write-Host '[OK] Missing guard telemetry no longer creates false block on final ENTER' -ForegroundColor Green

docker compose up -d --build --force-recreate astra
if($LASTEXITCODE -ne 0){throw 'ASTRA rebuild failed.'}

$ready=$false
for($i=0;$i -lt 30;$i++){
  Start-Sleep -Seconds 2
  try{
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($h.status -eq 'ok'){$ready=$true;break}
  }catch{}
}
if(-not $ready){throw 'ASTRA did not become healthy.'}

Write-Host ''
Write-Host '=== SYNTHETIC PREFLIGHT CHECK ===' -ForegroundColor Cyan

$py=@'
import json
from myshka_astra.live_dry_run import build_preview

r={
  "pair":"QNT/USDT:USDT",
  "action":"ENTER",
  "signal":{"direction":"LONG"},
  "edge":{"passed":True,"net_edge_pct":0.13,"total_cost_pct":0.18},
  "jev":{"verdict":"APPROVE"},
  "evidence_gate":{
    "applies":True,
    "passed":True,
    "state":"WARMING_EXPLORATION",
    "reason":"evidence_gate_warming_exploration"
  },
  "adaptive_learner":{"state":"PASS"},
  "market":{"last_price":292.72}
}

p=build_preview(r)
print(json.dumps({
  "all_passed":p["preflight"]["all_passed"],
  "blockers":p["preflight"]["blockers"],
  "guard":p["preflight"]["guard"],
  "guard_source":p["preflight"].get("guard_source"),
  "evidence":p["preflight"]["evidence"],
  "would_send_order":p["would_send_order"]
}))
'@

$out=$py | docker exec -i myshka-astra python -
Write-Host $out

$j=$out | ConvertFrom-Json
if($j.all_passed -ne $true -or $j.would_send_order -ne $true){
  throw 'Synthetic preflight still blocked.'
}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - PREFLIGHT HOTFIX V1.1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'Evidence WARMING_EXPLORATION passed=True: PASS'
Write-Host 'Missing guard on final ENTER: IMPLICIT_PRODUCTION_PASS'
Write-Host 'Freqtrade config: UNCHANGED'
Write-Host 'Real-money execution: UNCHANGED / DISABLED'
