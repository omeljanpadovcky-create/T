from pathlib import Path
import re
import sys

MARKER = "MYSHKA_LIVE_DRY_RUN_V1"


def _insert_after_line(s: str, pattern: str, addition: str, label: str) -> str:
    m = re.search(pattern, s, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"{label} not found")
    return s[:m.end()] + addition + s[m.end():]


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] api.py already has LIVE DRY RUN V1")
        return

    # Import after a known shadow-module import. Prefer Rescue, then Forward Lab,
    # then Risk Intelligence.
    import_line = (
        "from .live_dry_run import init as live_dry_run_init, status as live_dry_run_status, "
        "recent as live_dry_run_recent, observe_results as live_dry_run_observe\n"
    )
    import_patterns = [
        r"^from \.rescue_matrix import .*\n",
        r"^from \.forward_experiment_lab import .*\n",
        r"^from \.risk_intelligence_shadow import .*\n",
    ]
    done = False
    for pat in import_patterns:
        if re.search(pat, s, flags=re.MULTILINE):
            s = _insert_after_line(s, pat, import_line, "shadow import")
            done = True
            break
    if not done:
        raise RuntimeError("No suitable ASTRA shadow import anchor found")

    # Startup init after a known init call.
    for pat in (
        r"^[ \t]+rescue_matrix_init\(\)\n",
        r"^[ \t]+forward_experiment_init\(\)\n",
        r"^[ \t]+risk_intelligence_init\(\)\n",
    ):
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + f"{indent}# {MARKER}\n{indent}live_dry_run_init()\n" + s[m.end():]
            break
    else:
        raise RuntimeError("No suitable startup init anchor found")

    # Health entry after a known shadow status entry when available.
    health_patterns = [
        r'^[ \t]+"rescue_matrix":\s*rescue_matrix_status\(\),\n',
        r'^[ \t]+"forward_experiment_lab":\s*forward_experiment_status\(\),\n',
        r'^[ \t]+"risk_intelligence_shadow":\s*risk_intelligence_status\(\),\n',
    ]
    for pat in health_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + f'{indent}"live_dry_run": live_dry_run_status(),\n' + s[m.end():]
            break

    # Read-only endpoints.
    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/live-dry-run/status")\n'
        'def live_dry_run_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return live_dry_run_status()\n\n\n'
        '@app.get("/live-dry-run/recent")\n'
        'def live_dry_run_recent_api(limit: int = 50, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return live_dry_run_recent(limit=limit)\n\n\n'
    )
    endpoint_anchors = [
        '@app.get("/rescue-matrix/status")\n',
        '@app.get("/forward-experiments/status")\n',
        '@app.get("/risk-intelligence/status")\n',
    ]
    for a in endpoint_anchors:
        if a in s:
            s = s.replace(a, endpoints + a, 1)
            break
    else:
        raise RuntimeError("No suitable endpoint anchor found")

    # Observe normal scan results late in the shadow chain. This function returns
    # diagnostics only and never mutates results/actions.
    observer_patterns = [
        r"^[ \t]+risk_intelligence_observe\(results\)\n",
        r"^[ \t]+forward_experiment_observe\(results\)\n",
        r"^[ \t]+binance_crosscheck_observe\(results\)\n",
    ]
    for pat in observer_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + (
                f"{indent}# {MARKER}: would-send preview only; hard-blocked execution\n"
                f"{indent}live_dry_run_observe(results)\n"
            ) + s[m.end():]
            break
    else:
        raise RuntimeError("No suitable observer anchor found")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: LIVE DRY RUN V1 (execution hard-blocked)")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_live_dry_run.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
