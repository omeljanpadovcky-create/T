from pathlib import Path
import sys

MARKER = "MYSHKA_RISK_INTELLIGENCE_SHADOW_V1"


def replace_once(s: str, old: str, new: str, label: str) -> str:
    if old not in s:
        raise RuntimeError(f"patch target not found: {label}")
    return s.replace(old, new, 1)


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] api.py already has Risk Intelligence SHADOW")
        return

    cf_import = (
        "from .counterfactual_shadow import init as counterfactual_init, status as counterfactual_status, "
        "report as counterfactual_report, recent as counterfactual_recent, observe_results as counterfactual_observe\n"
    )
    ri_import = (
        "from .risk_intelligence_shadow import init as risk_intelligence_init, status as risk_intelligence_status, "
        "report as risk_intelligence_report, observe_results as risk_intelligence_observe\n"
    )
    s = replace_once(s, cf_import, cf_import + ri_import, "risk intelligence import")

    s = replace_once(
        s,
        "    counterfactual_init()\n    _start_phone_threads()\n",
        f"    counterfactual_init()\n    # {MARKER}\n    risk_intelligence_init()\n    _start_phone_threads()\n",
        "startup risk intelligence init",
    )

    s = replace_once(
        s,
        '        "counterfactual_shadow": counterfactual_status(),\n',
        '        "counterfactual_shadow": counterfactual_status(),\n        "risk_intelligence_shadow": risk_intelligence_status(),\n',
        "health risk intelligence status",
    )

    cf_recent_block = (
        '@app.get("/counterfactual/recent")\n'
        'def counterfactual_recent_api(limit: int = 50, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return {"status": "ok", "items": counterfactual_recent(limit)}\n\n\n'
    )
    endpoints = (
        '@app.get("/risk-intelligence/status")\n'
        'def risk_intelligence_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return risk_intelligence_status()\n\n\n'
        '@app.get("/risk-intelligence/report")\n'
        'def risk_intelligence_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return risk_intelligence_report()\n\n\n'
    )
    s = replace_once(s, cf_recent_block, cf_recent_block + endpoints, "risk intelligence endpoints")

    observer = (
        "# MYSHKA_COUNTERFACTUAL_SHADOW_V1: observe rejected candidates using the same normal scan results\n"
        "        counterfactual_observe(results)\n"
    )
    if observer not in s:
        # fall back to any indentation if current engine uses a different nesting level
        needle = "counterfactual_observe(results)\n"
        pos = s.find(needle)
        if pos < 0:
            raise RuntimeError("counterfactual observer call not found")
        line_start = s.rfind("\n", 0, pos) + 1
        line = s[line_start:pos]
        indent = line[: len(line) - len(line.lstrip(" \t"))]
        insertion = f"{indent}# {MARKER}: unified guard observer\n{indent}risk_intelligence_observe(results)\n"
        insert_at = pos + len(needle)
        s = s[:insert_at] + insertion + s[insert_at:]
    else:
        replacement = observer + (
            "        # " + MARKER + ": unified guard observer\n"
            "        risk_intelligence_observe(results)\n"
        )
        s = replace_once(s, observer, replacement, "risk intelligence observer")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Risk Intelligence SHADOW + API (no trading rule changes)")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_risk_intelligence_shadow.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
