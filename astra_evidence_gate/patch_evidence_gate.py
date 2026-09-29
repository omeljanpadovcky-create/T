from pathlib import Path
import sys

MARKER = "MYSHKA_EVIDENCE_GATE_V1"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if MARKER in s:
        print("[OK] Evidence Gate V1 already present")
        return

    hard_import = (
        "from .system_hardening import init as hardening_init, status as hardening_status, "
        "report as hardening_report, observe_results as hardening_observe\n"
    )
    evidence_import = (
        "from .evidence_gate import status as evidence_gate_status, report as evidence_gate_report, "
        "apply_results as evidence_gate_apply\n"
    )
    if hard_import not in s:
        raise RuntimeError("Final Hardening import not found. Install Final Hardening V1 first.")
    s = s.replace(hard_import, hard_import + evidence_import, 1)

    health_anchor = '        "hardening": hardening_status(),\n'
    if health_anchor not in s:
        raise RuntimeError("hardening health anchor not found")
    s = s.replace(
        health_anchor,
        health_anchor + f'        # {MARKER}\n        "evidence_gate": evidence_gate_status(),\n',
        1,
    )

    hard_status_block = (
        '@app.get("/hardening/status")\n'
        'def hardening_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return hardening_report(engine=phone_engine_status(), runtime=runtime_get(), integrations=None, do_reconcile=False)\n\n\n'
    )
    if hard_status_block not in s:
        raise RuntimeError("hardening status endpoint anchor not found")

    endpoints = (
        '@app.get("/evidence-gate/status")\n'
        'def evidence_gate_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return evidence_gate_status()\n\n\n'
        '@app.get("/evidence-gate/report")\n'
        'def evidence_gate_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return evidence_gate_report()\n\n\n'
    )
    s = s.replace(hard_status_block, endpoints + hard_status_block, 1)

    observer = "        counterfactual_observe(results)\n"
    if observer not in s:
        raise RuntimeError("counterfactual observer call not found")
    s = s.replace(
        observer,
        f"        # {MARKER}: active PAPER validation gate before all observers / position opening\n"
        "        evidence_gate_apply(results)\n"
        + observer,
        1,
    )

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Evidence Gate V1 active for STRICT PAPER ENTER only")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_evidence_gate.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
