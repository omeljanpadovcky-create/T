from pathlib import Path
import sys

MARKER = "MYSHKA_POST_CALIBRATION_V2_DASHBOARD"


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")

    if MARKER in s:
        print("[OK] POST-Calibration V2 dashboard API already present")
        return

    old_import = (
        "from .multihorizon_shadow import init as multihorizon_init, status as multihorizon_status, "
        "report as multihorizon_report, observe_results as multihorizon_observe\n"
    )
    new_import = (
        "from .multihorizon_shadow import init as multihorizon_init, status as multihorizon_status, "
        "report as multihorizon_report, post_calibration_report, observe_results as multihorizon_observe\n"
    )
    if old_import not in s:
        raise RuntimeError("Multi-Horizon import anchor not found")
    s = s.replace(old_import, new_import, 1)

    anchor = (
        '@app.get("/multihorizon/report")\n'
        'def multihorizon_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return multihorizon_report()\n\n\n'
    )
    if anchor not in s:
        raise RuntimeError("Multi-Horizon report endpoint anchor not found")

    endpoint = (
        f'# {MARKER}\n'
        '@app.get("/post-calibration/report")\n'
        'def post_calibration_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return post_calibration_report()\n\n\n'
    )
    s = s.replace(anchor, anchor + endpoint, 1)

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: /post-calibration/report")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_post_calibration_dashboard.py <ASTRA_PROJECT_DIR>")
    patch_api(Path(sys.argv[1]).resolve() / "api.py")


if __name__ == "__main__":
    main()
