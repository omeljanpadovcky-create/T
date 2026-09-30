from pathlib import Path
import re
import sys

MARKER = "MYSHKA_FREQTRADE_LIVE_BRIDGE_V1"


def _insert_after_line(s: str, pattern: str, addition: str, label: str) -> str:
    m = re.search(pattern, s, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"{label} not found")
    return s[:m.end()] + addition + s[m.end():]


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if MARKER in s:
        print("[OK] api.py already has Freqtrade LIVE Bridge V1")
        return

    dry_import = r"^from \.freqtrade_dryrun_bridge import .+\n"
    armed_import = r"^from \.live_armed_preflight import .+\n"
    if re.search(dry_import, s, flags=re.MULTILINE):
        anchor = dry_import
    elif re.search(armed_import, s, flags=re.MULTILINE):
        anchor = armed_import
    else:
        raise RuntimeError("Freqtrade dry-run/live-armed import anchor not found")

    import_line = (
        "from .freqtrade_live_bridge import init as freqtrade_live_init, "
        "status as freqtrade_live_status, recent as freqtrade_live_recent, "
        "preflight as freqtrade_live_preflight, observe_results as freqtrade_live_observe\n"
    )
    s = _insert_after_line(s, anchor, import_line, "live bridge import")

    init_patterns = [
        r"^[ \t]+freqtrade_dryrun_init\(\)\n",
        r"^[ \t]+live_armed_init\(\)\n",
    ]
    for pat in init_patterns:
        if re.search(pat, s, flags=re.MULTILINE):
            s = _insert_after_line(
                s, pat,
                f"    # {MARKER}\n    freqtrade_live_init()\n",
                "live bridge init",
            )
            break
    else:
        raise RuntimeError("live bridge init anchor not found")

    health_patterns = [
        r'^[ \t]+"freqtrade_dryrun_bridge":\s*freqtrade_dryrun_status\(\),\n',
        r'^[ \t]+"live_armed_preflight":\s*live_armed_status\(\),\n',
    ]
    for pat in health_patterns:
        if re.search(pat, s, flags=re.MULTILINE):
            s = _insert_after_line(
                s, pat,
                f'        # {MARKER}\n        "freqtrade_live_bridge": freqtrade_live_status(),\n',
                "live bridge health",
            )
            break
    else:
        raise RuntimeError("live bridge health anchor not found")

    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/freqtrade-live/status")\n'
        'def freqtrade_live_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return freqtrade_live_status()\n\n\n'
        '@app.get("/freqtrade-live/recent")\n'
        'def freqtrade_live_recent_api(limit: int = 50, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return freqtrade_live_recent(limit=limit)\n\n\n'
        '@app.get("/freqtrade-live/preflight")\n'
        'def freqtrade_live_preflight_api(pair: str, side: str, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return freqtrade_live_preflight(pair, side)\n\n\n'
    )

    route_anchors = [
        '@app.get("/freqtrade-dryrun/status")\n',
        '@app.get("/live-armed/status")\n',
    ]
    for a in route_anchors:
        if a in s:
            s = s.replace(a, endpoints + a, 1)
            break
    else:
        raise RuntimeError("live bridge endpoint anchor not found")

    obs_patterns = [
        r"^[ \t]+freqtrade_dryrun_observe\(results\)\n",
        r"^[ \t]+live_dry_run_observe\(results\)\n",
    ]
    for pat in obs_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + (
                f"{indent}# {MARKER}: guarded real-money route, disabled unless explicitly armed\n"
                f"{indent}freqtrade_live_observe(results)\n"
            ) + s[m.end():]
            break
    else:
        raise RuntimeError("live bridge observer anchor not found")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Freqtrade LIVE Bridge V1")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_freqtrade_live_bridge.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
