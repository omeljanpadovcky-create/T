$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - TELEGRAM SCAN SUMMARY V2 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=(docker inspect myshka-astra | ConvertFrom-Json)[0].Config.Labels.'com.docker.compose.project.working_dir'
if(-not $app){throw 'ASTRA project folder not found.'}
Set-Location $app

$target=Join-Path $app 'telegram_notify.py'
if(-not (Test-Path $target)){throw 'telegram_notify.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=$target+'.before-scan-summary-v2-'+$stamp
Copy-Item $target $backup -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$patcher = @'
from pathlib import Path
import sys

p = Path("telegram_notify.py")
s = p.read_text(encoding="utf-8")

marker = "MYSHKA_TELEGRAM_SCAN_SUMMARY_V2"
if marker in s:
    print("[OK] Telegram summary V2 already installed")
    sys.exit(0)

needle = '    return "\n".join(lines)'
idx = s.find(needle)
if idx < 0:
    raise SystemExit('formatter return anchor not found')

block = r'''    # MYSHKA_TELEGRAM_SCAN_SUMMARY_V2
    _scan_lines = [str(_x) for _x in lines]

    _pairs = sum(1 for _x in _scan_lines if _x.startswith("TECH: "))
    _directional = sum(
        1 for _x in _scan_lines
        if _x.startswith("TECH: LONG") or _x.startswith("TECH: SHORT")
    )
    _edge_pass = sum(1 for _x in _scan_lines if _x.startswith("EDGE: PASS"))
    _edge_drop = sum(1 for _x in _scan_lines if _x.startswith("EDGE: DROP"))
    _jev_approve = sum(1 for _x in _scan_lines if _x.startswith("JEV: APPROVE"))
    _enter = sum(1 for _x in _scan_lines if _x.startswith("FINAL: ENTER"))

    if _pairs > 0:
        if _directional == 0:
            _bottleneck = "TECH"
        elif _edge_pass == 0:
            _bottleneck = "EDGE"
        elif _jev_approve == 0:
            _bottleneck = "JEV"
        elif _enter == 0:
            _bottleneck = "EVIDENCE / GUARD / ADAPTIVE"
        else:
            _bottleneck = "NONE - ENTER present"

        lines.append("")
        lines.append("\U0001F4CA SCAN SUMMARY")
        lines.append(f"Pairs: {_pairs}")
        lines.append(f"TECH directional: {_directional}")
        lines.append(f"EDGE PASS: {_edge_pass}")
        lines.append(f"EDGE DROP: {_edge_drop}")
        lines.append(f"JEV APPROVE: {_jev_approve}")
        lines.append(f"ENTER: {_enter}")
        lines.append("")
        lines.append(f"\U0001F6A7 Bottleneck: {_bottleneck}")

'''

s = s[:idx] + block + s[idx:]
p.write_text(s, encoding="utf-8")
print("[OK] Telegram scan summary V2 inserted")
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

$check=Select-String -Path $target -Pattern 'MYSHKA_TELEGRAM_SCAN_SUMMARY_V2|SCAN SUMMARY|Bottleneck'
if(-not $check){
  Copy-Item $backup $target -Force
  throw 'Patch marker not found. Backup restored.'
}
Write-Host '[OK] Patch marker found' -ForegroundColor Green

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
Write-Host ' READY - TELEGRAM SCAN SUMMARY V2 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'Trading logic: UNCHANGED'
Write-Host 'Telegram formatter only: UPDATED'
