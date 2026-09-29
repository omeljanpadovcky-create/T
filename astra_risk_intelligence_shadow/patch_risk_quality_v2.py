from pathlib import Path
import re
import sys

MARKER = "MYSHKA_RISK_QUALITY_V2"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if MARKER in s:
        print("[OK] Risk Quality V2 endpoints already present")
        return

    old_import = re.search(
        r"from \.risk_intelligence_shadow import init as risk_intelligence_init, status as risk_intelligence_status,\s*"
        r"report as risk_intelligence_report, observe_results as risk_intelligence_observe\n",
        s,
    )
    if not old_import:
        raise RuntimeError("Risk Intelligence import not found in api.py")

    new_import = (
        "from .risk_intelligence_shadow import init as risk_intelligence_init, status as risk_intelligence_status, "
        "report as risk_intelligence_report, quality_report as risk_intelligence_quality_report, "
        "replay as risk_intelligence_replay, observe_results as risk_intelligence_observe\n"
    )
    s = s[:old_import.start()] + new_import + s[old_import.end():]

    report_block = (
        '@app.get("/risk-intelligence/report")\n'
        'def risk_intelligence_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return risk_intelligence_report()\n\n\n'
    )
    if report_block not in s:
        raise RuntimeError("Risk Intelligence report endpoint not found")

    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/risk-intelligence/quality")\n'
        'def risk_intelligence_quality_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return risk_intelligence_quality_report()\n\n\n'
        '@app.get("/risk-intelligence/replay")\n'
        'def risk_intelligence_replay_api(limit: int = 20, decision_id: Optional[int] = None, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return risk_intelligence_replay(limit=limit, decision_id=decision_id)\n\n\n'
    )
    s = s.replace(report_block, report_block + endpoints, 1)

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Risk Quality V2 + Black Box replay endpoints")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_risk_quality_v2.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
