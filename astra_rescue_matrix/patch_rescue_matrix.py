from pathlib import Path
import re, sys

MARKER="MYSHKA_RESCUE_MATRIX_V1"

def patch_api(path: Path):
    s=path.read_text(encoding="utf-8-sig")
    compile(s,str(path),"exec")
    if MARKER in s:
        print("[OK] RESCUE MATRIX V1 already present")
        return

    m=re.search(r"^from \.risk_intelligence_shadow import .*\n",s,flags=re.MULTILINE)
    if not m:
        raise RuntimeError("Risk Intelligence import not found")
    imp="from .rescue_matrix import init as rescue_matrix_init, status as rescue_matrix_status, report as rescue_matrix_report\n"
    s=s[:m.end()]+imp+s[m.end():]

    # Startup: initialize immediately after risk intelligence when possible.
    startup=re.search(r"^[ \t]+risk_intelligence_init\(\)\n",s,flags=re.MULTILINE)
    if startup:
        s=s[:startup.end()]+f"    # {MARKER}\n    rescue_matrix_init()\n"+s[startup.end():]
    else:
        raise RuntimeError("risk_intelligence_init() startup call not found")

    # Health status.
    health=re.search(r'^[ \t]+"risk_intelligence_shadow":\s*risk_intelligence_status\(\),\n',s,flags=re.MULTILINE)
    if health:
        s=s[:health.end()]+f'        # {MARKER}\n        "rescue_matrix": rescue_matrix_status(),\n'+s[health.end():]

    endpoints=(
        f'# {MARKER}\n'
        '@app.get("/rescue-matrix/status")\n'
        'def rescue_matrix_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return rescue_matrix_status()\n\n\n'
        '@app.get("/rescue-matrix/report")\n'
        'def rescue_matrix_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return rescue_matrix_report()\n\n\n'
    )
    anchor='@app.get("/risk-intelligence/status")\n'
    if anchor not in s:
        anchor='@app.get("/risk-intelligence/report")\n'
    if anchor not in s:
        raise RuntimeError("Risk Intelligence endpoint anchor not found")
    s=s.replace(anchor,endpoints+anchor,1)

    compile(s,str(path),"exec")
    path.write_text(s,encoding="utf-8")
    print("[OK] api.py patched: RESCUE MATRIX V1 SHADOW")

def main():
    if len(sys.argv)!=2:
        raise SystemExit("usage: patch_rescue_matrix.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve()/"api.py")

if __name__=="__main__":
    main()
