from pathlib import Path
import re
import sys

MARKER = "MYSHKA_FASTTRACK_PAPER_CANARY_V1"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] api.py already has FastTrack PAPER Canary V1")
        return

    import_line = (
        "from .fasttrack_paper_canary import init as fasttrack_canary_init, "
        "status as fasttrack_canary_status, recent as fasttrack_canary_recent, "
        "observe_results as fasttrack_canary_observe\n"
    )

    import_anchors = [
        r"^from \.freqtrade_dryrun_bridge import .*\n",
        r"^from \.forward_experiment_lab import .*\n",
        r"^from \.binance_signal_crosscheck import .*\n",
        r"^from \.live_dry_run import .*\n",
    ]
    for pat in import_anchors:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            s = s[:m.end()] + import_line + s[m.end():]
            break
    else:
        raise RuntimeError("No import anchor found for FastTrack canary")

    init_anchors = [
        r"^[ \t]+freqtrade_dryrun_init\(\)\n",
        r"^[ \t]+forward_experiment_init\(\)\n",
        r"^[ \t]+binance_crosscheck_init\(\)\n",
        r"^[ \t]+live_dry_run_init\(\)\n",
    ]
    for pat in init_anchors:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + f"{indent}# {MARKER}\n{indent}fasttrack_canary_init()\n" + s[m.end():]
            break
    else:
        raise RuntimeError("No init anchor found for FastTrack canary")

    health_anchors = [
        r'^[ \t]+"freqtrade_dryrun_bridge":\s*freqtrade_dryrun_status\(\),\n',
        r'^[ \t]+"forward_experiment_lab":\s*forward_experiment_status\(\),\n',
        r'^[ \t]+"binance_crosscheck":\s*binance_crosscheck_status\(\),\n',
    ]
    for pat in health_anchors:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + f'{indent}"fasttrack_paper_canary": fasttrack_canary_status(),\n' + s[m.end():]
            break
    else:
        raise RuntimeError("No health anchor found for FastTrack canary")

    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/fasttrack-canary/status")\n'
        'def fasttrack_canary_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return fasttrack_canary_status()\n\n\n'
        '@app.get("/fasttrack-canary/recent")\n'
        'def fasttrack_canary_recent_api(limit: int = 50, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return fasttrack_canary_recent(limit=limit)\n\n\n'
    )

    endpoint_anchors = [
        '@app.get("/freqtrade-dryrun/status")\n',
        '@app.get("/forward-experiment-lab/status")\n',
        '@app.get("/binance-crosscheck/status")\n',
        '@app.get("/live-dry-run/status")\n',
    ]
    for anchor in endpoint_anchors:
        if anchor in s:
            s = s.replace(anchor, endpoints + anchor, 1)
            break
    else:
        raise RuntimeError("No endpoint anchor found for FastTrack canary")

    observer_patterns = [
        r"^[ \t]+freqtrade_dryrun_observe\(results\)\n",
        r"^[ \t]+forward_experiment_observe\(results\)\n",
        r"^[ \t]+binance_crosscheck_observe\(results\)\n",
    ]
    for pat in observer_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + (
                f"{indent}# {MARKER}: isolated PAPER canary observer\n"
                f"{indent}fasttrack_canary_observe(results)\n"
            ) + s[m.end():]
            break
    else:
        raise RuntimeError("No observer anchor found for FastTrack canary")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: FastTrack PAPER Canary V1")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_fasttrack_paper_canary.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
