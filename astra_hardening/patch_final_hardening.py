from pathlib import Path
import re
import sys

MARKER = "MYSHKA_FINAL_HARDENING_V1"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if MARKER in s:
        print("[OK] Final Hardening V1 already present")
        return

    ri_import = re.search(
        r"from \.risk_intelligence_shadow import init as risk_intelligence_init, status as risk_intelligence_status,\s*"
        r"report as risk_intelligence_report, quality_report as risk_intelligence_quality_report,\s*"
        r"replay as risk_intelligence_replay, observe_results as risk_intelligence_observe\n",
        s,
    )
    if not ri_import:
        raise RuntimeError("Risk Quality V2 import not found. Install/upgrade Risk Quality V2 first.")

    hard_import = (
        "from .system_hardening import init as hardening_init, status as hardening_status, "
        "report as hardening_report, observe_results as hardening_observe\n"
    )
    s = s[:ri_import.end()] + hard_import + s[ri_import.end():]

    startup_old = "    risk_intelligence_init()\n    _start_phone_threads()\n"
    startup_new = (
        "    risk_intelligence_init()\n"
        f"    # {MARKER}\n"
        "    hardening_init()\n"
        "    _start_phone_threads()\n"
    )
    if startup_old not in s:
        raise RuntimeError("Risk Intelligence startup anchor not found")
    s = s.replace(startup_old, startup_new, 1)

    health_old = '        "risk_intelligence_shadow": risk_intelligence_status(),\n'
    if health_old not in s:
        raise RuntimeError("Risk Intelligence health anchor not found")
    s = s.replace(
        health_old,
        health_old + '        "hardening": hardening_status(),\n',
        1,
    )

    replay_block = (
        '@app.get("/risk-intelligence/replay")\n'
        'def risk_intelligence_replay_api(limit: int = 20, decision_id: Optional[int] = None, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return risk_intelligence_replay(limit=limit, decision_id=decision_id)\n\n\n'
    )
    if replay_block not in s:
        raise RuntimeError("Risk replay endpoint anchor not found")

    endpoints = (
        'class HardeningReconcileRequest(BaseModel):\n'
        '    integrations: dict = Field(default_factory=dict)\n\n\n'
        '@app.get("/hardening/status")\n'
        'def hardening_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return hardening_report(engine=phone_engine_status(), runtime=runtime_get(), integrations=None, do_reconcile=False)\n\n\n'
        '@app.post("/hardening/reconcile")\n'
        'def hardening_reconcile_api(req: HardeningReconcileRequest, x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return hardening_report(engine=phone_engine_status(), runtime=runtime_get(), integrations=req.integrations, do_reconcile=True)\n\n\n'
    )
    s = s.replace(replay_block, replay_block + endpoints, 1)

    obs = "        risk_intelligence_observe(results)\n"
    if obs not in s:
        raise RuntimeError("Risk Intelligence observer call not found")
    hard_obs = (
        obs
        + "        hardening_observe(results, config_snapshot={\n"
        + '            "universe_target": 15,\n'
        + '            "timeframe": str(getattr(CONFIG, "TIMEFRAME", "1m")),\n'
        + '            "candle_limit": int(getattr(CONFIG, "CANDLE_LIMIT", 80)),\n'
        + '            "scan_interval_sec": 15,\n'
        + '            "review_horizon_sec": 300,\n'
        + '            "strict_min_net_edge_pct": 0.05,\n'
        + '            "training_until_trades": getattr(CONFIG, "TRAINING_UNTIL_TRADES", None),\n'
        + '            "training_min_tech_conditions": getattr(CONFIG, "TRAINING_MIN_TECH_CONDITIONS", None),\n'
        + "        })\n"
    )
    s = s.replace(obs, hard_obs, 1)

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Final Hardening V1 (diagnostic only)")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_final_hardening.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
