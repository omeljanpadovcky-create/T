from pathlib import Path
import re
import sys

MARKER = "MYSHKA_BINANCE_SIGNAL_CROSSCHECK_V1"


def _insert_after_line(s: str, pattern: str, addition: str, label: str) -> str:
    m = re.search(pattern, s, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"{label} not found")
    return s[:m.end()] + addition + s[m.end():]


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if MARKER in s:
        print("[OK] Binance Signal Crosscheck V1 already present")
        return

    # 1) Import: tolerate both original Multi-Horizon import and the later
    # POST-Calibration variant that also imports post_calibration_report.
    if not re.search(r"^from \.multihorizon_shadow import .+$", s, flags=re.MULTILINE):
        raise RuntimeError("Multi-Horizon module import not found")
    bx_import = (
        "from .binance_signal_crosscheck import init as binance_crosscheck_init, "
        "status as binance_crosscheck_status, report as binance_crosscheck_report, "
        "observe_results as binance_crosscheck_observe\n"
    )
    s = _insert_after_line(
        s,
        r"^from \.multihorizon_shadow import .+\n",
        bx_import,
        "Multi-Horizon import",
    )

    # 2) Startup: insert directly after the existing init call regardless of
    # what modules were added later before _start_phone_threads().
    s = _insert_after_line(
        s,
        r"^[ \t]+multihorizon_init\(\)\n",
        f"    # {MARKER}\n    binance_crosscheck_init()\n",
        "Multi-Horizon startup",
    )

    # 3) Health.
    s = _insert_after_line(
        s,
        r'^[ \t]+"multihorizon_shadow":\s*multihorizon_status\(\),\n',
        f'        # {MARKER}\n        "binance_crosscheck": binance_crosscheck_status(),\n',
        "Multi-Horizon health entry",
    )

    # 4) Endpoints: POST-Calibration V2 is installed on this project, so use
    # its route as a stable insertion point. Fall back to multihorizon route.
    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/binance-crosscheck/status")\n'
        'def binance_crosscheck_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return binance_crosscheck_status()\n\n\n'
        '@app.get("/binance-crosscheck/report")\n'
        'def binance_crosscheck_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return binance_crosscheck_report()\n\n\n'
    )
    post_route = '@app.get("/post-calibration/report")\n'
    mh_route = '@app.get("/multihorizon/report")\n'
    if post_route in s:
        s = s.replace(post_route, endpoints + post_route, 1)
    elif mh_route in s:
        s = s.replace(mh_route, endpoints + mh_route, 1)
    else:
        raise RuntimeError("Multi-Horizon/Post-Calibration endpoint insertion point not found")

    # 5) Observer: insert directly after the Multi-Horizon observer call.
    # This is SHADOW and never changes r['action'].
    s = _insert_after_line(
        s,
        r"^[ \t]+multihorizon_observe\(results\)\n",
        f"        # {MARKER}: diagnostic crosscheck only; never changes action\n"
        "        binance_crosscheck_observe(results)\n",
        "Multi-Horizon observer call",
    )

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Binance Signal Crosscheck V1 SHADOW")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_binance_signal_crosscheck.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
