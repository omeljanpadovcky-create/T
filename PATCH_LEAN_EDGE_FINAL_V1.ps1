$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$env:COMPOSE_ANSI='never'
$env:BUILDKIT_PROGRESS='plain'

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - LEAN EDGE FINAL V1 ' -ForegroundColor Yellow
Write-Host ' REMOVE VOL MULTIPLIERS ONLY - STILL DRY_RUN ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=$null
try{
  $raw=docker inspect myshka-astra 2>$null | ConvertFrom-Json
  if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
    $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
  }
}catch{}
if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path $fallback){$app=$fallback}
}
if(-not $app){throw 'ASTRA project folder not found.'}
Set-Location $app

$envFile=Join-Path $app '.env.live-armed'
if(-not (Test-Path $envFile)){throw '.env.live-armed not found.'}
$envText=Get-Content $envFile -Raw
if($envText -notmatch '(?m)^FREQTRADE__DRY_RUN=true\s*$'){throw 'HARD STOP: FREQTRADE__DRY_RUN is not true.'}
if($envText -notmatch '(?m)^ASTRA_FASTTRACK_EXECUTION_MODE=DRY_RUN\s*$'){throw 'HARD STOP: FastTrack execution mode is not DRY_RUN.'}
if($envText -notmatch '(?m)^ASTRA_LIVE_EXECUTION=false\s*$'){throw 'HARD STOP: ASTRA_LIVE_EXECUTION is not false.'}
if($envText -notmatch '(?m)^ASTRA_LIVE_KILL_SWITCH=true\s*$'){throw 'HARD STOP: ASTRA_LIVE_KILL_SWITCH is not true.'}

$edge=Join-Path $app 'edge.py'
if(-not (Test-Path $edge)){
  $candidates=@(
    Get-ChildItem -Path $app -Filter 'edge.py' -File -Recurse -ErrorAction SilentlyContinue |
      Where-Object {$_.FullName -notmatch '\\backup-' -and $_.FullName -notmatch '\\\.venv\\' -and $_.FullName -notmatch '\\__pycache__\\'} |
      Sort-Object {$_.FullName.Length}
  )
  if($candidates.Count -lt 1){throw 'edge.py not found.'}
  $edge=$candidates[0].FullName
}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backupDir=Join-Path $app ('backup-before-lean-edge-final-v1-'+$stamp)
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
Copy-Item $edge (Join-Path $backupDir 'edge.py') -Force

Write-Host ('[1/6] Target: '+$edge)

$src=Get-Content $edge -Raw
$marker='MYSHKA_LEAN_EDGE_FINAL_V1'

if($src -notmatch [regex]::Escape($marker)){
  $pattern='(?ms)^def estimate_costs\(\s*spread_pct:\s*float,\s*atr_pct:\s*float,\s*atr_pct_median:\s*float\s*\)\s*->\s*float:\s*\r?\n.*?(?=^def estimate_expected_move\()'
  $replacement=@'
def estimate_costs(spread_pct: float, atr_pct: float, atr_pct_median: float) -> float:
    """Round-trip taker fee + measured spread + fixed slippage + fixed safety margin.

    MYSHKA_LEAN_EDGE_FINAL_V1
    Deliberately keeps the existing base values and removes only the two
    volatility multipliers. Signature is unchanged for compatibility.
    """
    slippage = CONFIG.BASE_SLIPPAGE_PCT
    safety_margin = CONFIG.EDGE_SAFETY_MARGIN_BASE_PCT
    return CONFIG.ROUND_TRIP_TAKER_FEE_PCT + spread_pct + slippage + safety_margin


'@
  $patched=[regex]::Replace($src,$pattern,$replacement,1)
  if($patched -eq $src){throw 'Could not locate estimate_costs() safely. No changes made.'}
  Set-Content -Path $edge -Value $patched -Encoding UTF8
  Write-Host '[OK] Removed volatility multipliers only.' -ForegroundColor Green
}else{
  Write-Host '[OK] LEAN EDGE final patch already installed.' -ForegroundColor Green
}

Write-Host '[2/6] Compiling patched edge.py...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& python -m py_compile $edge
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){
  Copy-Item (Join-Path $backupDir 'edge.py') $edge -Force
  throw 'Python compile failed. Original edge.py restored.'
}
Write-Host '[OK] Python compile passed.' -ForegroundColor Green

Write-Host '[3/6] Rebuilding ASTRA only...'
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
& docker compose --ansi never up -d --build --force-recreate astra
$rc=$LASTEXITCODE
$ErrorActionPreference=$old
if($rc -ne 0){throw 'ASTRA rebuild failed.'}

Write-Host '[4/6] Waiting for ASTRA health...'
$ready=$false
for($i=0;$i -lt 60;$i++){
  Start-Sleep -Seconds 2
  try{
    $h=Invoke-RestMethod 'http://127.0.0.1:8088/health' -TimeoutSec 5
    if($h.status -eq 'ok'){$ready=$true;break}
  }catch{}
}
if(-not $ready){throw 'ASTRA did not become healthy.'}
Write-Host '[OK] ASTRA healthy.' -ForegroundColor Green

Write-Host '[5/6] Verifying effective EDGE function in container...'
$verify=@'
import inspect, json
import myshka_astra.edge as e

src=inspect.getsource(e.estimate_costs)
low=e.estimate_costs(0.02,0.10,0.10)
high=e.estimate_costs(0.02,0.50,0.10)

print(json.dumps({
    "marker": "MYSHKA_LEAN_EDGE_FINAL_V1" in src,
    "cost_normal_vol": low,
    "cost_high_vol": high,
    "same_cost_across_volatility": abs(low-high) < 1e-12,
    "source": src
}, indent=2))
'@
$old=$ErrorActionPreference
$ErrorActionPreference='Continue'
$verifyOut=$verify | docker exec -i myshka-astra python -
$vrc=$LASTEXITCODE
$ErrorActionPreference=$old
if($vrc -ne 0){throw 'Could not verify patched EDGE in container.'}
$v=$verifyOut | ConvertFrom-Json
if(-not $v.marker){throw 'LEAN EDGE marker not active in running container.'}
if(-not $v.same_cost_across_volatility){throw 'Volatility still changes EDGE costs.'}

Write-Host ('[OK] Cost @ spread 0.02% normal vol: '+$v.cost_normal_vol+'%') -ForegroundColor Green
Write-Host ('[OK] Cost @ spread 0.02% high vol:   '+$v.cost_high_vol+'%') -ForegroundColor Green
Write-Host '[OK] Volatility multipliers are gone.' -ForegroundColor Green

Write-Host '[6/6] DRY_RUN funnel check...'
$token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object {$_ -match '^MYSHKA_BRIDGE_TOKEN='} | ForEach-Object {$_.Substring($_.IndexOf('=')+1)} | Select-Object -First 1)
if(-not $token){throw 'MYSHKA_BRIDGE_TOKEN not found.'}
$headers=@{'X-MYSHKA-TOKEN'=$token}

$first=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
$base=$first.live_funnel
$baseAgree=[int]$base.binance_agree
$baseReject=[int]$base.jev_shadow_edge_reject
$baseJev=[int]$base.jev_approve
$baseTriple=[int]$base.triple_eligible
$baseSent=[int]$base.sent

for($i=1;$i -le 12;$i++){
  Start-Sleep -Seconds 15
  $s=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
  $f=$s.live_funnel
  Write-Host ("sample="+$i+" scan="+$f.scan_calls+" tech3="+$f.tech3+" agree="+$f.binance_agree+" edgeReject="+$f.jev_shadow_edge_reject+" jev="+$f.jev_approve+" triple="+$f.triple_eligible+" sent="+$f.sent+" last="+$f.last_stage+" jevsrc="+$f.last_jev_source)
  if(([int]$f.sent -gt $baseSent) -or ([int]$f.jev_approve -gt $baseJev)){break}
}

$final=Invoke-RestMethod 'http://127.0.0.1:8088/fasttrack-canary/status' -Headers $headers -TimeoutSec 10
$ff=$final.live_funnel

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - LEAN EDGE FINAL V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'Formula: taker round-trip fee + actual spread + fixed base slippage + fixed base safety'
Write-Host ('Base slippage: '+0.03+'% (existing config)')
Write-Host ('Base safety:   '+0.03+'% (existing config)')
Write-Host ('Delta Binance AGREE: '+([int]$ff.binance_agree-$baseAgree))
Write-Host ('Delta EDGE rejects:  '+([int]$ff.jev_shadow_edge_reject-$baseReject))
Write-Host ('Delta JEV approve:   '+([int]$ff.jev_approve-$baseJev))
Write-Host ('Delta triple:        '+([int]$ff.triple_eligible-$baseTriple))
Write-Host ('Delta sent:          '+([int]$ff.sent-$baseSent))
Write-Host 'REAL MONEY: OFF'
Write-Host 'KILL SWITCH: ON'
Write-Host ('Backup: '+$backupDir)
