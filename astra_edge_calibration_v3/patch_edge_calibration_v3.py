from pathlib import Path
import sys

MARKER = "MYSHKA_EDGE_CALIBRATION_V3"
OLD_IMPORT = "from .edge_calibration_v2 import apply as edge_calibration_apply, status as edge_calibration_status\n"
NEW_IMPORT = (
    "from .edge_calibration_v3 import apply as edge_calibration_apply, "
    "status as edge_calibration_status, report as edge_calibration_report\n"
)


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] API already has EDGE Calibration V3")
        return

    if OLD_IMPORT not in s:
        raise RuntimeError("EDGE Calibration V2 import anchor not found. Install V2 first.")
    s = s.replace(OLD_IMPORT, NEW_IMPORT, 1)

    health_old = '        "edge_calibration_v2": edge_calibration_status(),\n'
    if health_old not in s:
        raise RuntimeError("EDGE Calibration V2 health anchor not found")
    health_new = (
        f'        # {MARKER}\n'
        '        "edge_calibration_v2": {**edge_calibration_status(), "compat_alias": "v3"},\n'
        '        "edge_calibration_v3": edge_calibration_status(),\n'
    )
    s = s.replace(health_old, health_new, 1)

    report_anchor = (
        '@app.get("/multihorizon/status")\n'
        'def multihorizon_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
    )
    if report_anchor not in s:
        raise RuntimeError("Multi-horizon endpoint anchor not found")
    report_ep = (
        '@app.get("/edge-calibration-v3/report")\n'
        'def edge_calibration_v3_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return edge_calibration_report()\n\n\n'
    )
    s = s.replace(report_anchor, report_ep + report_anchor, 1)

    s = s.replace(
        'training_meta["edge_calibration_v2"] = edge_calibration',
        'training_meta["edge_calibration_v3"] = edge_calibration',
        1,
    )
    s = s.replace(
        '"edge_calibration_v2": edge_calibration, "training": training_meta,',
        '"edge_calibration_v3": edge_calibration, "training": training_meta,',
        1,
    )

    decision_anchor = "    # MYSHKA_EDGE_CALIBRATION_V2: PAPER calibration before JEV; can only reject, never create ENTER\n"
    if decision_anchor in s:
        s = s.replace(
            decision_anchor,
            decision_anchor + f"    # {MARKER}: clustered isotonic V3 replaces manual V2 band\n",
            1,
        )
    else:
        if "edge_calibration = edge_calibration_apply(" not in s:
            raise RuntimeError("EDGE calibration decision call not found")
        s = s.replace(
            "    edge_calibration = edge_calibration_apply(\n",
            f"    # {MARKER}: clustered isotonic V3 replaces manual V2 band\n"
            "    edge_calibration = edge_calibration_apply(\n",
            1,
        )

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: EDGE Calibration V3 active for PAPER decisions")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_edge_calibration_v3.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")
    print("[OK] EDGE Calibration V3 API patch complete")


if __name__ == "__main__":
    main()
