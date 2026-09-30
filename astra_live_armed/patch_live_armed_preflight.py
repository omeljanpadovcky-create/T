from pathlib import Path
import re
import sys

MARKER = "MYSHKA_LIVE_ARMED_PREFLIGHT_V1"

def _insert_after_line(s: str, pattern: str, addition: str, label: str) -> str:
    m = re.search(pattern, s, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"{label} not found")
    return s[:m.end()] + addition + s[m.end():]

def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if MARKER in s:
        print("[OK] api.py already has LIVE ARMED PREFLIGHT V1")
        return

    import_line = (
        "from .live_armed_preflight import init as live_armed_init, status as live_armed_status, "
        "preflight as live_armed_preflight, build_forceenter_preview as live_armed_preview\n"
    )
    patterns = [
        r"^from \.live_dry_run import .*\n",
        r"^from \.rescue_matrix import .*\n",
        r"^from \.forward_experiment_lab import .*\n",
    ]
    for pat in patterns:
        if re.search(pat, s, flags=re.MULTILINE):
            s = _insert_after_line(s, pat, import_line, "import anchor")
            break
    else:
        raise RuntimeError("No suitable import anchor found")

    init_patterns = [
        r"^[ \t]+live_dry_run_init\(\)\n",
        r"^[ \t]+rescue_matrix_init\(\)\n",
        r"^[ \t]+forward_experiment_init\(\)\n",
    ]
    for pat in init_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + f"{indent}# {MARKER}\n{indent}live_armed_init()\n" + s[m.end():]
            break
    else:
        raise RuntimeError("No suitable init anchor found")

    health_patterns = [
        r'^[ \t]+"live_dry_run":\s*live_dry_run_status\(\),\n',
        r'^[ \t]+"rescue_matrix":\s*rescue_matrix_status\(\),\n',
    ]
    for pat in health_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + f'{indent}"live_armed_preflight": live_armed_status(),\n' + s[m.end():]
            break

    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/live-armed/status")\n'
        'def live_armed_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return live_armed_status()\n\n\n'
        '@app.get("/live-armed/preflight")\n'
        'def live_armed_preflight_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return live_armed_preflight()\n\n\n'
        '@app.get("/live-armed/preview")\n'
        'def live_armed_preview_api(pair: str, side: str, stake_usdt: float = 10.0, leverage: float = 1.0, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return live_armed_preview(pair, side, stake_usdt=stake_usdt, leverage=leverage)\n\n\n'
    )
    anchors = [
        '@app.get("/live-dry-run/status")\n',
        '@app.get("/rescue-matrix/status")\n',
        '@app.get("/forward-experiments/status")\n',
    ]
    for a in anchors:
        if a in s:
            s = s.replace(a, endpoints + a, 1)
            break
    else:
        raise RuntimeError("No endpoint anchor found")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: LIVE ARMED PREFLIGHT V1 (read-only + manual confirmation)")

def main():
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_live_armed_preflight.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")

if __name__ == "__main__":
    main()
