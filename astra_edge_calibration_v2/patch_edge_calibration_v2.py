from pathlib import Path
import sys

API_MARKER = "MYSHKA_EDGE_CALIBRATION_V2"
JEV_MARKER = "MYSHKA_OLLAMA_PERCENT_UNITS_V2"
MH_MARKER = "MYSHKA_MULTIHORIZON_SHADOW_V1"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if API_MARKER not in s:
        learner_import = (
            "from .adaptive_learner import init as adaptive_learner_init, status as adaptive_learner_status, "
            "report as adaptive_learner_report, recent_snapshots as adaptive_learner_recent, "
            "apply_results as adaptive_learner_apply\n"
        )
        imports = (
            "from .edge_calibration_v2 import apply as edge_calibration_apply, status as edge_calibration_status\n"
            "from .multihorizon_shadow import init as multihorizon_init, status as multihorizon_status, "
            "report as multihorizon_report, observe_results as multihorizon_observe\n"
        )
        if learner_import not in s:
            raise RuntimeError("Adaptive Learner import not found. Install Adaptive ML Learner V1 first.")
        s = s.replace(learner_import, learner_import + imports, 1)

        startup = "    adaptive_learner_init()\n    _start_phone_threads()\n"
        if startup not in s:
            raise RuntimeError("Adaptive Learner startup anchor not found")
        s = s.replace(
            startup,
            "    adaptive_learner_init()\n"
            f"    # {MH_MARKER}\n"
            "    multihorizon_init()\n"
            "    _start_phone_threads()\n",
            1,
        )

        health = '        "adaptive_learner": adaptive_learner_status(),\n'
        if health not in s:
            raise RuntimeError("Adaptive Learner health anchor not found")
        s = s.replace(
            health,
            health
            + f'        # {API_MARKER}\n'
            + '        "edge_calibration_v2": edge_calibration_status(),\n'
            + '        "multihorizon_shadow": multihorizon_status(),\n',
            1,
        )

        endpoint_anchor = (
            '@app.get("/adaptive-learner/recent")\n'
            'def adaptive_learner_recent_api(limit: int = 20, x_myshka_token: Optional[str] = Header(default=None)):\n'
            '    _require_token(x_myshka_token)\n'
            '    return {"status":"ok","items":adaptive_learner_recent(limit)}\n\n\n'
        )
        if endpoint_anchor not in s:
            raise RuntimeError("Adaptive Learner endpoint anchor not found")
        endpoints = (
            '@app.get("/edge-calibration/status")\n'
            'def edge_calibration_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
            '    _require_token(x_myshka_token)\n'
            '    return edge_calibration_status()\n\n\n'
            '@app.get("/multihorizon/status")\n'
            'def multihorizon_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
            '    _require_token(x_myshka_token)\n'
            '    return multihorizon_status()\n\n\n'
            '@app.get("/multihorizon/report")\n'
            'def multihorizon_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
            '    _require_token(x_myshka_token)\n'
            '    return multihorizon_report()\n\n\n'
        )
        s = s.replace(endpoint_anchor, endpoint_anchor + endpoints, 1)

        jev_anchor = "    # JEV is the chief decision coordinator."
        if jev_anchor not in s:
            raise RuntimeError("JEV decision anchor not found")
        calibration_block = (
            f"    # {API_MARKER}: PAPER calibration before JEV; can only reject, never create ENTER\n"
            "    edge_calibration = edge_calibration_apply(\n"
            "        signal=sig, edge=edge, candles=req.candles,\n"
            "        atr_pct=req.atr_pct, atr_median_pct=req.atr_pct_median,\n"
            "    )\n"
            "    training_meta[\"edge_calibration_v2\"] = edge_calibration\n"
            "    if edge_calibration.get(\"applies\") and not edge_calibration.get(\"passed\"):\n"
            "        edge_payload = _clean(edge.as_dict()) if edge is not None else None\n"
            "        if isinstance(edge_payload, dict):\n"
            "            edge_payload[\"passed\"] = False\n"
            "            edge_payload[\"reason\"] = edge_calibration.get(\"reason\")\n"
            "            edge_payload[\"calibration_v2\"] = edge_calibration\n"
            "        return {\n"
            "            \"action\": \"DROP\", \"reason\": edge_calibration.get(\"reason\"), \"pair\": req.pair,\n"
            "            \"signal\": _clean(sig.as_dict()), \"edge\": edge_payload,\n"
            "            \"edge_calibration_v2\": edge_calibration, \"training\": training_meta,\n"
            "        }\n\n"
        )
        s = s.replace(jev_anchor, calibration_block + jev_anchor, 1)

        flow = "        adaptive_learner_apply(results)\n        counterfactual_observe(results)\n"
        if flow not in s:
            raise RuntimeError("Adaptive/Counterfactual flow anchor not found")
        s = s.replace(
            flow,
            "        adaptive_learner_apply(results)\n"
            f"        # {MH_MARKER}: 5m/10m/15m SHADOW outcomes from normal scan prices\n"
            "        multihorizon_observe(results)\n"
            "        counterfactual_observe(results)\n",
            1,
        )

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")


def patch_jev(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if JEV_MARKER in s:
        return

    old = (
        '        "Be conservative. Do not override hard risk controls. Context: " + json.dumps(payload)\n'
    )
    new = (
        f'        "Be conservative. Do not override hard risk controls. "  # {JEV_MARKER}\n'
        '        "IMPORTANT UNITS: every numeric field ending in _pct is already expressed in percentage points. " \n'
        '        "For example net_edge_pct=0.098 means +0.098%, NOT 9.8%. Never multiply *_pct values by 100. " \n'
        '        "Context: " + json.dumps(payload)\n'
    )
    if old not in s:
        raise RuntimeError("Ollama prompt anchor not found")
    s = s.replace(old, new, 1)
    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_edge_calibration_v2.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")
    patch_jev(root / "jev.py")
    print("[OK] EDGE Calibration V2 patched")
    print("[OK] Ollama percentage units patched")
    print("[OK] Multi-Horizon SHADOW patched")


if __name__ == "__main__":
    main()
