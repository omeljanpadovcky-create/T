from pathlib import Path
import re
import sys

MARKER = "MYSHKA_EXECUTION_SLIPPAGE_AUDIT_V1"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] api.py already has execution slippage audit V1")
        return

    import_line = (
        "from .execution_slippage_audit import status as slippage_audit_status, "
        "recent as slippage_audit_recent\n"
    )

    anchors = [
        r"^from \.freqtrade_dryrun_bridge import .*\n",
        r"^from \.freqtrade_live_bridge import .*\n",
        r"^from \.live_dry_run import .*\n",
    ]
    for pat in anchors:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            s = s[:m.end()] + import_line + s[m.end():]
            break
    else:
        raise RuntimeError("No import anchor found for slippage audit")

    health_patterns = [
        r'^[ \t]+"freqtrade_dryrun_bridge":\s*freqtrade_dryrun_status\(\),\n',
        r'^[ \t]+"freqtrade_live_bridge":\s*freqtrade_live_status\(\),\n',
        r'^[ \t]+"live_dry_run":\s*live_dry_run_status\(\),\n',
    ]
    for pat in health_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]+", m.group(0)).group(0)
            s = s[:m.end()] + (
                f'{indent}# {MARKER}\n'
                f'{indent}"execution_slippage_audit": slippage_audit_status(),\n'
            ) + s[m.end():]
            break
    else:
        raise RuntimeError("No health anchor found for slippage audit")

    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/slippage-audit/status")\n'
        'def slippage_audit_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return slippage_audit_status()\n\n\n'
        '@app.get("/slippage-audit/recent")\n'
        'def slippage_audit_recent_api(limit: int = 50, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return slippage_audit_recent(limit=limit)\n\n\n'
    )

    endpoint_anchors = [
        '@app.get("/freqtrade-dryrun/status")\n',
        '@app.get("/freqtrade-live/status")\n',
        '@app.get("/live-dry-run/status")\n',
    ]
    for anchor in endpoint_anchors:
        if anchor in s:
            s = s.replace(anchor, endpoints + anchor, 1)
            break
    else:
        raise RuntimeError("No endpoint anchor found for slippage audit")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: execution slippage audit V1")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_execution_slippage_audit.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
