from pathlib import Path
import re
import sys

MARKER = "MYSHKA_FORWARD_EXPERIMENT_LAB_V1"


def _insert_after_line(s: str, pattern: str, addition: str, label: str) -> str:
    m = re.search(pattern, s, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"{label} not found")
    return s[:m.end()] + addition + s[m.end():]


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if MARKER in s:
        print("[OK] Forward Experiment Lab V1 already present")
        return

    bx_import_re = (
        r"^from \.binance_signal_crosscheck import init as binance_crosscheck_init, "
        r"status as binance_crosscheck_status, report as binance_crosscheck_report, "
        r"observe_results as binance_crosscheck_observe\n"
    )
    if not re.search(bx_import_re, s, flags=re.MULTILINE):
        raise RuntimeError("Binance Crosscheck import not found. Install X-Check first.")

    lab_import = (
        "from .forward_experiment_lab import init as forward_experiment_init, "
        "status as forward_experiment_status, report as forward_experiment_report, "
        "recent as forward_experiment_recent, observe_results as forward_experiment_observe\n"
    )
    s = _insert_after_line(s, bx_import_re, lab_import, "Binance X-Check import")

    s = _insert_after_line(
        s,
        r"^[ \t]+binance_crosscheck_init\(\)\n",
        f"    # {MARKER}\n    forward_experiment_init()\n",
        "Binance X-Check startup",
    )

    s = _insert_after_line(
        s,
        r'^[ \t]+"binance_crosscheck":\s*binance_crosscheck_status\(\),\n',
        f'        # {MARKER}\n        "forward_experiment_lab": forward_experiment_status(),\n',
        "Binance X-Check health entry",
    )

    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/forward-experiments/status")\n'
        'def forward_experiments_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return forward_experiment_status()\n\n\n'
        '@app.get("/forward-experiments/report")\n'
        'def forward_experiments_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return forward_experiment_report()\n\n\n'
        '@app.get("/forward-experiments/recent")\n'
        'def forward_experiments_recent_api(limit: int = 100, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return forward_experiment_recent(limit=limit)\n\n\n'
    )
    anchor = '@app.get("/post-calibration/report")\n'
    if anchor not in s:
        anchor = '@app.get("/binance-crosscheck/status")\n'
    if anchor not in s:
        raise RuntimeError("Forward Experiment endpoint insertion point not found")
    s = s.replace(anchor, endpoints + anchor, 1)

    # Run after Binance X-Check so the lab can capture AGREE/CONFLICT/NEUTRAL.
    s = _insert_after_line(
        s,
        r"^[ \t]+binance_crosscheck_observe\(results\)\n",
        f"        # {MARKER}: forward-only SHADOW evidence; never changes action\n"
        "        forward_experiment_observe(results)\n",
        "Binance X-Check observer call",
    )

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Forward Experiment Lab V1 SHADOW")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_forward_experiment_lab.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
