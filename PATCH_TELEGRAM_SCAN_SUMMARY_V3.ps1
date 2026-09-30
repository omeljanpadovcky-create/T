$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - TELEGRAM SCAN SUMMARY V3 ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=(docker inspect myshka-astra | ConvertFrom-Json)[0].Config.Labels.'com.docker.compose.project.working_dir'
if(-not $app){throw 'ASTRA project folder not found.'}
Set-Location $app

$target=Join-Path $app 'telegram_notify.py'
if(-not (Test-Path $target)){throw 'telegram_notify.py not found.'}

$stamp=Get-Date -Format 'yyyyMMdd-HHmmss'
$backup=$target+'.before-scan-summary-v3-'+$stamp
Copy-Item $target $backup -Force
Write-Host ('[OK] Backup: '+$backup) -ForegroundColor Green

$patcher = @'
from pathlib import Path
import ast, sys

p = Path("telegram_notify.py")
s = p.read_text(encoding="utf-8")
marker = "MYSHKA_TELEGRAM_SCAN_SUMMARY_V3"

if marker in s:
    print("[OK] Telegram summary V3 already installed")
    sys.exit(0)

tree = ast.parse(s)

target_func = None
target_return = None

def has_final_marker(node):
    for x in ast.walk(node):
        if isinstance(x, ast.Constant) and isinstance(x.value, str) and "FINAL:" in x.value:
            return True
    return False

for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and has_final_marker(node):
        returns = [x for x in ast.walk(node) if isinstance(x, ast.Return)]
        if returns:
            target_func = node
            target_return = max(returns, key=lambda x: getattr(x, "lineno", 0))
            break

if target_func is None or target_return is None:
    raise SystemExit("Could not locate Telegram formatter function/return via AST")

lines = s.splitlines(True)
insert_at = target_return.lineno - 1
indent = " " * (target_return.col_offset or 4)

block_lines = [
f'{indent}# {marker}\n',
f'{indent}_scan_lines = [str(_x) for _x in lines]\n',
f'{indent}_pairs = sum(1 for _x in _scan_lines if _x.startswith("TECH: "))\n',
f'{indent}_directional = sum(1 for _x in _scan_lines if _x.startswith("TECH: LONG") or _x.startswith("TECH: SHORT"))\n',
f'{indent}_edge_pass = sum(1 for _x in _scan_lines if _x.startswith("EDGE: PASS"))\n',
f'{indent}_edge_drop = sum(1 for _x in _scan_lines if _x.startswith("EDGE: DROP"))\n',
f'{indent}_jev_approve = sum(1 for _x in _scan_lines if _x.startswith("JEV: APPROVE"))\n',
f'{indent}_enter = sum(1 for _x in _scan_lines if _x.startswith("FINAL: ENTER"))\n',
f'{indent}if _pairs > 0:\n',
f'{indent}    if _directional == 0:\n',
f'{indent}        _bottleneck = "TECH"\n',
f'{indent}    elif _edge_pass == 0:\n',
f'{indent}        _bottleneck = "EDGE"\n',
f'{indent}    elif _jev_approve == 0:\n',
f'{indent}        _bottleneck = "JEV"\n',
f'{indent}    elif _enter == 0:\n',
f'{indent}        _bottleneck = "EVIDENCE / GUARD / ADAPTIVE"\n',
f'{indent}    else:\n',
f'{indent}        _bottleneck = "NONE - ENTER present"\n',
f'{indent}    lines.append("")\n',
f'{indent}    lines.append("\\U0001F4CA SCAN SUMMARY")\n',
f'{indent}    lines.append(f"Pairs: {{_pairs}}")\n',
f'{indent}    lines.append(f"TECH directional: {{_directional}}")\n',
f'{indent}    lines.append(f"EDGE PASS: {{_edge_pass}}")\n',
f'{indent}    lines.append(f"EDGE DROP: {{_edge_drop}}")\n',
f'{indent}    lines.append(f"JEV APPROVE: {{_jev_approve}}")\n',
f'{indent}    lines.append(f"ENTER: {{_enter}}")\n',
f'{indent}    lines.append("")\n',
f'{indent}    lines.append(f"\\U0001F6A7 Bottleneck: {{_bottleneck}}")\n',
'\n'
]

lines[insert_at:insert_at] = block_lines
p.write_text("".join(lines), encoding="utf-8")
print("[OK] AST formatter function:", target_func.name)
print("[OK] Inserted before source line:", target_return.lineno)
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

$check=Select-String -Path $target -Pattern 'MYSHKA_TELEGRAM_SCAN_SUMMARY_V3|SCAN SUMMARY|Bottleneck'
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
Write-Host ' READY - TELEGRAM SCAN SUMMARY V3 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host 'Trading logic: UNCHANGED'
Write-Host 'Telegram formatter only: UPDATED'
