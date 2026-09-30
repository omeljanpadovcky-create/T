from pathlib import Path
import re
import sys

MARKER = "MYSHKA_FREQTRADE_DRYRUN_BRIDGE_V1"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] api.py already has Freqtrade DRY-RUN bridge V1")
        return

    import_line = (
        "from .freqtrade_dryrun_bridge import init as freqtrade_dryrun_init, "
        "status as freqtrade_dryrun_status, recent as freqtrade_dryrun_recent, "
        "smoke as freqtrade_dryrun_smoke, observe_results as freqtrade_dryrun_observe\n"
    )

    import_anchors = [
        r"^from \.live_dry_run import .*\n",
        r"^from \.live_armed_preflight import .*\n",
        r"^from \.rescue_matrix import .*\n",
    ]
    for pat in import_anchors:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            s = s[:m.end()] + import_line + s[m.end():]
            break
    else:
        raise RuntimeError("No suitable import anchor found")

    init_anchors = [
        r"^[ \t]+live_dry_run_init\(\)\n",
        r"^[ \t]+live_armed_init\(\)\n",
        r"^[ \t]+rescue_matrix_init\(\)\n",
    ]
    for pat in init_anchors:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + f"{indent}# {MARKER}\n{indent}freqtrade_dryrun_init()\n" + s[m.end():]
            break
    else:
        raise RuntimeError("No suitable init anchor found")

    health_patterns = [
        r'^[ \t]+"live_dry_run":\s*live_dry_run_status\(\),\n',
        r'^[ \t]+"live_armed_preflight":\s*live_armed_status\(\),\n',
        r'^[ \t]+"rescue_matrix":\s*rescue_matrix_status\(\),\n',
    ]
    for pat in health_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + f'{indent}"freqtrade_dryrun_bridge": freqtrade_dryrun_status(),\n' + s[m.end():]
            break

    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/freqtrade-dryrun/status")\n'
        'def freqtrade_dryrun_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return freqtrade_dryrun_status()\n\n\n'
        '@app.get("/freqtrade-dryrun/recent")\n'
        'def freqtrade_dryrun_recent_api(limit: int = 50, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return freqtrade_dryrun_recent(limit=limit)\n\n\n'
        '@app.post("/freqtrade-dryrun/smoke")\n'
        'def freqtrade_dryrun_smoke_api(pair: str, side: str, confirm: str, stake_usdt: float = 10.0, leverage: float = 1.0, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return freqtrade_dryrun_smoke(pair, side, confirm, stake_usdt=stake_usdt, leverage=leverage)\n\n\n'
    )

    endpoint_anchors = [
        '@app.get("/live-dry-run/status")\n',
        '@app.get("/live-armed/status")\n',
        '@app.get("/rescue-matrix/status")\n',
    ]
    for a in endpoint_anchors:
        if a in s:
            s = s.replace(a, endpoints + a, 1)
            break
    else:
        raise RuntimeError("No endpoint anchor found")

    observer_patterns = [
        r"^[ \t]+live_dry_run_observe\(results\)\n",
        r"^[ \t]+risk_intelligence_observe\(results\)\n",
        r"^[ \t]+forward_experiment_observe\(results\)\n",
    ]
    for pat in observer_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + (
                f"{indent}# {MARKER}: gated Freqtrade DRY-RUN execution only\n"
                f"{indent}freqtrade_dryrun_observe(results)\n"
            ) + s[m.end():]
            break
    else:
        raise RuntimeError("No observer anchor found")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Freqtrade DRY-RUN bridge V1")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_freqtrade_dryrun_bridge.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
