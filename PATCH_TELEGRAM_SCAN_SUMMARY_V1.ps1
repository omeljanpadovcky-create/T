$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - TELEGRAM SCAN SUMMARY V1 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=(docker inspect myshka-astra | ConvertFrom-Json)[0].Config.Labels.'com.docker.compose.project.working_dir'
if(-not $app){throw 'ASTRA project folder not found.'}
Set-Location $app

$target=Join-Path $app 'telegram_notify.py'
if(-not (Test-Path $target)){throw 'telegram_notify.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=$target+'.before-scan-summary-'+$stamp
Copy-Item $target $backup -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$patcher = @'
from pathlib import Path
import re, sys

p = Path("telegram_notify.py")
s = p.read_text(encoding="utf-8")

marker = "MYSHKA_TELEGRAM_SCAN_SUMMARY_V1"
if marker in s:
    print("[OK] Telegram summary already installed")
    sys.exit(0)

# Find the result-loop variable from the loop that builds per-pair Telegram blocks.
anchor = 'lines.append(f"📌 {pair}")'
pos = s.find(anchor)
if pos < 0:
    raise SystemExit("PAIR formatter anchor not found")

prefix = s[:pos]
matches = list(re.finditer(r'(?m)^    for r in ([A-Za-z_][A-Za-z0-9_]*)[^:]*:\s*$', prefix))
if not matches:
    raise SystemExit("Could not detect result loop variable")

loop_var = matches[-1].group(1)

needle = '    return "\\n".join(lines)'
ret = s.find(needle, pos)
if ret < 0:
    raise SystemExit("Formatter return anchor not found")

block = f'''    # {marker}
    _summary_rows = list({loop_var} or [])
    _pairs = len(_summary_rows)
    _directional = 0
    _tech4 = 0
    _edge_pass = 0
    _edge_drop = 0
    _jev_approve = 0
    _enter = 0

    for _r in _summary_rows:
        _sig = _r.get("signal") or {{}}
        _edge = _r.get("edge") or {{}}
        _jev = _r.get("jev") or {{}}

        _dir = str(_sig.get("direction") or "WAIT").upper()
        if _dir in {{"LONG", "SHORT"}}:
            _directional += 1

        try:
            if int(_sig.get("tech_score") or 0) == 4:
                _tech4 += 1
        except Exception:
            pass

        if _edge.get("passed") is True:
            _edge_pass += 1

        if str(_r.get("reason") or "").lower() == "strict_edge_buffer":
            _edge_drop += 1

        if str(_jev.get("verdict") or "").upper() == "APPROVE":
            _jev_approve += 1

        if str(_r.get("action") or "").upper() == "ENTER":
            _enter += 1

    if _pairs:
        if _directional == 0:
            _bottleneck = "TECH"
        elif _edge_pass == 0:
            _bottleneck = "EDGE"
        elif _jev_approve == 0:
            _bottleneck = "JEV"
        elif _enter == 0:
            _bottleneck = "EVIDENCE / GUARD / ADAPTIVE"
        else:
            _bottleneck = "NONE — є ENTER"

        lines.append("")
        lines.append("📊 SCAN SUMMARY")
        lines.append(f"Pairs: {{_pairs}}")
        lines.append(f"TECH directional: {{_directional}}")
        lines.append(f"TECH4: {{_tech4}}")
        lines.append(f"EDGE PASS: {{_edge_pass}}")
        lines.append(f"EDGE DROP: {{_edge_drop}}")
        lines.append(f"JEV APPROVE: {{_jev_approve}}")
        lines.append(f"ENTER: {{_enter}}")
        lines.append("")
        lines.append(f"🚧 Bottleneck: {{_bottleneck}}")

'''
s = s[:ret] + block + s[ret:]
p.write_text(s, encoding="utf-8")
print("[OK] Telegram scan summary inserted")
print("[OK] loop variable:", loop_var)
'@

$patcher | python -
if($LASTEXITCODE -ne 0){
  Copy-Item $backup $target -Force
  throw 'Patch failed. Backup restored.'
}

python -m py_compile $target
if($LASTEXITCODE -ne 0){
  Copy-Item $backup $target -Force
  throw 'Compile failed. Backup restored.'
}
Write-Host '[OK] telegram_notify.py compiles' -ForegroundColor Green

Write-Host ''
Write-Host '=== PATCH MARKER ===' -ForegroundColor Cyan
Select-String -Path $target -Pattern 'MYSHKA_TELEGRAM_SCAN_SUMMARY_V1|SCAN SUMMARY|Bottleneck' -Context 0,1

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
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - TELEGRAM SCAN SUMMARY V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'Trading logic: UNCHANGED'
Write-Host 'EDGE/JEV/Evidence/Guard/Adaptive: UNCHANGED'
Write-Host 'Telegram formatter only: UPDATED'
