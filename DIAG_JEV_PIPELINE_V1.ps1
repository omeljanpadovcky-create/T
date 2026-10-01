$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest

Write-Host '==========================================================' -ForegroundColor Cyan
Write-Host ' MYSHKA / ASTRA - JEV PIPELINE DIAGNOSTIC V1 ' -ForegroundColor Yellow
Write-Host ' READ ONLY - NO REBUILD - NO FILE CHANGES ' -ForegroundColor Yellow
Write-Host '==========================================================' -ForegroundColor Cyan

$app=$null
try{
  $old=$ErrorActionPreference
  $ErrorActionPreference='Continue'
  $rawText=& docker inspect myshka-astra 2>$null
  $rc=$LASTEXITCODE
  $ErrorActionPreference=$old
  if($rc -eq 0 -and $rawText){
    $raw=$rawText | ConvertFrom-Json
    if($raw -and $raw[0].Config.Labels.'com.docker.compose.project.working_dir'){
      $app=$raw[0].Config.Labels.'com.docker.compose.project.working_dir'
    }
  }
}catch{}

if(-not $app){
  $fallback=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_ASTRA_v9_4_PHONE_FULL\MYSHKA_ASTRA_v9_4_PHONE_FULL'
  if(Test-Path (Join-Path $fallback 'api.py')){$app=$fallback}
}
if(-not $app){throw 'ASTRA project folder not found.'}

Write-Host ('[OK] ASTRA project: '+$app) -ForegroundColor Green
Write-Host ''

$py = @'
from pathlib import Path
import ast
import json
import os
import re
import sys

root = Path(sys.argv[1])
patterns = re.compile(r"\bjev\b|ollama|APPROVE|REJECT|verdict", re.I)

def context(lines, idx, radius=4):
    lo=max(0, idx-radius)
    hi=min(len(lines), idx+radius+1)
    return "\n".join(f"{i+1:5d}: {lines[i]}" for i in range(lo,hi))

files=[]
for p in root.glob("*.py"):
    try:
        txt=p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        continue
    if patterns.search(txt):
        files.append(p)

print("=== MATCHING FILES ===")
for p in files:
    print(p.name)

print("\n=== API.PY JEV / OLLAMA CONTEXT ===")
api=root/"api.py"
if api.exists():
    lines=api.read_text(encoding="utf-8", errors="replace").splitlines()
    hits=[i for i,l in enumerate(lines) if patterns.search(l)]
    shown=set()
    for i in hits:
        block=(max(0,i-4),min(len(lines),i+5))
        if block in shown:
            continue
        shown.add(block)
        print("\n---")
        print(context(lines,i,4))

    print("\n=== API.PY FUNCTIONS CONTAINING JEV / OLLAMA ===")
    try:
        src="\n".join(lines)
        tree=ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                seg=ast.get_source_segment(src,node) or ""
                if patterns.search(seg):
                    print(f"{node.name} @ line {node.lineno}")
    except Exception as e:
        print("AST parse error:", type(e).__name__, str(e))
else:
    print("api.py not found")

print("\n=== OTHER PYTHON MATCHES ===")
for p in files:
    if p.name=="api.py":
        continue
    lines=p.read_text(encoding="utf-8", errors="replace").splitlines()
    hits=[i for i,l in enumerate(lines) if patterns.search(l)]
    print(f"\n### {p.name}")
    for i in hits[:16]:
        print(context(lines,i,2))
        print("---")

print("\n=== ENV KEY NAMES ONLY ===")
envp=root/".env.live-armed"
if envp.exists():
    for raw in envp.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" not in raw or raw.lstrip().startswith("#"):
            continue
        k=raw.split("=",1)[0].strip()
        if re.search(r"JEV|OLLAMA|AI|MODEL|NEWS",k,re.I):
            print(k)
'@

$tmp=Join-Path $env:TEMP 'myshka_jev_pipeline_diag_v1.py'
$py | Set-Content $tmp -Encoding UTF8

Write-Host '[1/2] Inspecting local Python pipeline...'
$out=& python $tmp $app

$save=Join-Path $env:USERPROFILE 'Downloads\MYSHKA_JEV_PIPELINE_DIAG.txt'
$out | Set-Content $save -Encoding UTF8

Write-Host '[2/2] Runtime control snapshot...'
try{
  $token=(docker inspect myshka-astra --format '{{range .Config.Env}}{{println .}}{{end}}' | Where-Object { $_ -match '^MYSHKA_BRIDGE_TOKEN=' } | ForEach-Object { $_.Substring($_.IndexOf('=')+1) } | Select-Object -First 1)
  if($token){
    $headers=@{'X-MYSHKA-TOKEN'=$token}
    $ctl=Invoke-RestMethod 'http://127.0.0.1:8088/control/status' -Headers $headers -TimeoutSec 8
    Write-Host ('runtime ollama_enabled: '+$ctl.runtime.ollama_enabled)
    Write-Host ('runtime auto_scan: '+$ctl.runtime.auto_scan)
    Write-Host ('runtime paused: '+$ctl.runtime.paused)
  }
}catch{
  Write-Host ('[WARN] control/status unavailable: '+$_.Exception.Message) -ForegroundColor Yellow
}

Write-Host ''
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ' READY - JEV PIPELINE DIAGNOSTIC V1 ' -ForegroundColor Green
Write-Host '==========================================================' -ForegroundColor Green
Write-Host ('Saved: '+$save)
Write-Host ''
$out
Write-Host ''
Write-Host 'Files changed: NO'
Write-Host 'Docker rebuild: NO'
Write-Host 'Trading decisions changed: NO'
Write-Host 'LIVE changed: NO'
