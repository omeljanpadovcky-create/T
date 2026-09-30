from pathlib import Path
import sys

MARKER = "MYSHKA_BINANCE_SIGNAL_CROSSCHECK_V1"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if MARKER in s:
        print("[OK] Binance Signal Crosscheck V1 already present")
        return

    import_anchor = (
        "from .multihorizon_shadow import init as multihorizon_init, status as multihorizon_status, "
        "report as multihorizon_report, observe_results as multihorizon_observe\n"
    )
    new_import = (
        "from .binance_signal_crosscheck import init as binance_crosscheck_init, "
        "status as binance_crosscheck_status, report as binance_crosscheck_report, "
        "observe_results as binance_crosscheck_observe\n"
    )
    if import_anchor not in s:
        raise RuntimeError("Multi-Horizon import anchor not found. Install EDGE Calibration V2 first.")
    s = s.replace(import_anchor, import_anchor + new_import, 1)

    startup_anchor = "    multihorizon_init()\n    _start_phone_threads()\n"
    if startup_anchor not in s:
        raise RuntimeError("Multi-Horizon startup anchor not found")
    s = s.replace(
        startup_anchor,
        "    multihorizon_init()\n"
        f"    # {MARKER}\n"
        "    binance_crosscheck_init()\n"
        "    _start_phone_threads()\n",
        1,
    )

    health_anchor = '        "multihorizon_shadow": multihorizon_status(),\n'
    if health_anchor not in s:
        raise RuntimeError("Multi-Horizon health anchor not found")
    s = s.replace(
        health_anchor,
        health_anchor + f'        # {MARKER}\n        "binance_crosscheck": binance_crosscheck_status(),\n',
        1,
    )

    endpoint_anchor = (
        '@app.get("/multihorizon/report")\n'
        'def multihorizon_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return multihorizon_report()\n\n\n'
    )
    if endpoint_anchor not in s:
        raise RuntimeError("Multi-Horizon report endpoint anchor not found")
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
    s = s.replace(endpoint_anchor, endpoint_anchor + endpoints, 1)

    flow_anchor = (
        "        # MYSHKA_MULTIHORIZON_SHADOW_V1: 5m/10m/15m SHADOW outcomes from normal scan prices\n"
        "        multihorizon_observe(results)\n"
        "        counterfactual_observe(results)\n"
    )
    if flow_anchor not in s:
        # More tolerant fallback for already-patched variants.
        simple = "        multihorizon_observe(results)\n        counterfactual_observe(results)\n"
        if simple not in s:
            raise RuntimeError("Multi-Horizon observer flow anchor not found")
        replacement = (
            "        multihorizon_observe(results)\n"
            f"        # {MARKER}: diagnostic crosscheck only; never changes action\n"
            "        binance_crosscheck_observe(results)\n"
            "        counterfactual_observe(results)\n"
        )
        s = s.replace(simple, replacement, 1)
    else:
        replacement = (
            "        # MYSHKA_MULTIHORIZON_SHADOW_V1: 5m/10m/15m SHADOW outcomes from normal scan prices\n"
            "        multihorizon_observe(results)\n"
            f"        # {MARKER}: diagnostic crosscheck only; never changes action\n"
            "        binance_crosscheck_observe(results)\n"
            "        counterfactual_observe(results)\n"
        )
        s = s.replace(flow_anchor, replacement, 1)

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: Binance Signal Crosscheck V1 SHADOW")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_binance_signal_crosscheck.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
