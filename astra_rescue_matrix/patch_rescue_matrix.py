from pathlib import Path
import re
import sys

MARKER = "MYSHKA_RESCUE_MATRIX_V2"


def patch_api(path: Path):
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    import_line = "from .rescue_matrix import init as rescue_matrix_init, status as rescue_matrix_status, report as rescue_matrix_report\n"
    if import_line not in s:
        m = re.search(r"^from \.risk_intelligence_shadow import .*\n", s, flags=re.MULTILINE)
        if not m:
            raise RuntimeError("Risk Intelligence import not found")
        s = s[:m.end()] + import_line + s[m.end():]

    # Initialize once near Risk Intelligence startup. If an older Rescue marker is
    # already installed, keep the existing call and do not duplicate it.
    if "rescue_matrix_init()" not in s:
        startup = re.search(r"^[ \t]+risk_intelligence_init\(\)\n", s, flags=re.MULTILINE)
        if not startup:
            raise RuntimeError("risk_intelligence_init() startup call not found")
        indent = re.match(r"^[ \t]+", startup.group(0)).group(0)
        ins = f"{indent}# {MARKER}\n{indent}rescue_matrix_init()\n"
        s = s[:startup.end()] + ins + s[startup.end():]

    # Health status.
    if '"rescue_matrix": rescue_matrix_status(),' not in s:
        health = re.search(r'^[ \t]+"risk_intelligence_shadow":\s*risk_intelligence_status\(\),\n', s, flags=re.MULTILINE)
        if health:
            indent = re.match(r"^[ \t]+", health.group(0)).group(0)
            s = s[:health.end()] + f'{indent}# {MARKER}\n{indent}"rescue_matrix": rescue_matrix_status(),\n' + s[health.end():]

    # Endpoints are stable between V1 and V2.
    if '@app.get("/rescue-matrix/report")' not in s:
        endpoints = (
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
        anchor = '@app.get("/risk-intelligence/status")\n'
        if anchor not in s:
            anchor = '@app.get("/risk-intelligence/report")\n'
        if anchor not in s:
            raise RuntimeError("Risk Intelligence endpoint anchor not found")
        s = s.replace(anchor, endpoints + anchor, 1)

    if MARKER not in s:
        # Older V1 install may already have all wiring; add only a harmless marker.
        s = f"# {MARKER}\n" + s

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: RESCUE MATRIX V2 FORWARD SHADOW")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_rescue_matrix.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
