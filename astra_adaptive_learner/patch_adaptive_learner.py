from pathlib import Path
import sys

MARKER = "MYSHKA_ADAPTIVE_ML_LEARNER_V1"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] Adaptive ML Learner V1 already present")
        return

    evidence_import = (
        "from .evidence_gate import status as evidence_gate_status, report as evidence_gate_report, "
        "apply_results as evidence_gate_apply\n"
    )
    learner_import = (
        "from .adaptive_learner import init as adaptive_learner_init, status as adaptive_learner_status, "
        "report as adaptive_learner_report, recent_snapshots as adaptive_learner_recent, "
        "apply_results as adaptive_learner_apply\n"
    )
    if evidence_import not in s:
        raise RuntimeError("Evidence Gate V1 import not found. Install Evidence Gate V1 first.")
    s = s.replace(evidence_import, evidence_import + learner_import, 1)

    startup_anchor = "    hardening_init()\n    _start_phone_threads()\n"
    if startup_anchor not in s:
        raise RuntimeError("Final Hardening startup anchor not found")
    s = s.replace(
        startup_anchor,
        "    hardening_init()\n"
        f"    # {MARKER}\n"
        "    adaptive_learner_init()\n"
        "    _start_phone_threads()\n",
        1,
    )

    health_anchor = '        "evidence_gate": evidence_gate_status(),\n'
    if health_anchor not in s:
        raise RuntimeError("Evidence Gate health anchor not found")
    s = s.replace(
        health_anchor,
        health_anchor + '        "adaptive_learner": adaptive_learner_status(),\n',
        1,
    )

    evidence_report_block = (
        '@app.get("/evidence-gate/report")\n'
        'def evidence_gate_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return evidence_gate_report()\n\n\n'
    )
    if evidence_report_block not in s:
        raise RuntimeError("Evidence Gate endpoint anchor not found")

    endpoints = (
        '@app.get("/adaptive-learner/status")\n'
        'def adaptive_learner_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return adaptive_learner_status()\n\n\n'
        '@app.get("/adaptive-learner/report")\n'
        'def adaptive_learner_report_api(force: bool = False, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return adaptive_learner_report(force=force)\n\n\n'
        '@app.get("/adaptive-learner/recent")\n'
        'def adaptive_learner_recent_api(limit: int = 20, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return {"status":"ok","items":adaptive_learner_recent(limit)}\n\n\n'
    )
    s = s.replace(evidence_report_block, evidence_report_block + endpoints, 1)

    flow_anchor = (
        f"        # MYSHKA_EVIDENCE_GATE_V1: active PAPER validation gate before all observers / position opening\n"
        "        evidence_gate_apply(results)\n"
        "        counterfactual_observe(results)\n"
    )
    if flow_anchor not in s:
        raise RuntimeError("Evidence Gate flow anchor not found")

    flow_new = (
        "        # MYSHKA_EVIDENCE_GATE_V1: active PAPER validation gate before all observers / position opening\n"
        "        evidence_gate_apply(results)\n"
        f"        # {MARKER}: promoted ML policy may only further filter surviving PAPER ENTERs\n"
        "        adaptive_learner_apply(results)\n"
        "        counterfactual_observe(results)\n"
    )
    s = s.replace(flow_anchor, flow_new, 1)

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Adaptive ML Learner V1 after Evidence Gate; PAPER filter only")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_adaptive_learner.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
