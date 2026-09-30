from pathlib import Path
import ast
import re
import sys

API_MARKER = "MYSHKA_EXTERNAL_MARKET_SHADOW_V1"
TG_MARKER = "MYSHKA_EXTERNAL_MARKET_TG_V1"


def _insert_after_line(s: str, pattern: str, addition: str, label: str) -> str:
    m = re.search(pattern, s, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"{label} not found")
    return s[:m.end()] + addition + s[m.end():]


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if API_MARKER in s:
        print("[OK] api.py External Market Shadow already present")
        return

    bx_re = r"^from \.binance_signal_crosscheck import .+\n"
    mh_re = r"^from \.multihorizon_shadow import .+\n"
    import_anchor = bx_re if re.search(bx_re, s, flags=re.MULTILINE) else mh_re
    if not re.search(import_anchor, s, flags=re.MULTILINE):
        raise RuntimeError("Binance/Multi-Horizon import anchor not found")

    ext_import = (
        "from .external_market_shadow import init as external_market_init, "
        "status as external_market_status, report as external_market_report, "
        "observe_results as external_market_observe\n"
    )
    s = _insert_after_line(s, import_anchor, ext_import, "external import anchor")

    startup_patterns = [
        r"^[ \t]+binance_crosscheck_init\(\)\n",
        r"^[ \t]+multihorizon_init\(\)\n",
    ]
    for pat in startup_patterns:
        if re.search(pat, s, flags=re.MULTILINE):
            s = _insert_after_line(
                s, pat,
                f"    # {API_MARKER}\n    external_market_init()\n",
                "startup anchor",
            )
            break
    else:
        raise RuntimeError("startup anchor not found")

    health_patterns = [
        r'^[ \t]+"binance_crosscheck":\s*binance_crosscheck_status\(\),\n',
        r'^[ \t]+"multihorizon_shadow":\s*multihorizon_status\(\),\n',
    ]
    for pat in health_patterns:
        if re.search(pat, s, flags=re.MULTILINE):
            s = _insert_after_line(
                s, pat,
                f'        # {API_MARKER}\n        "external_market_shadow": external_market_status(),\n',
                "health anchor",
            )
            break
    else:
        raise RuntimeError("health anchor not found")

    endpoints = (
        f'# {API_MARKER}\n'
        '@app.get("/external-market/status")\n'
        'def external_market_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return external_market_status()\n\n\n'
        '@app.get("/external-market/report")\n'
        'def external_market_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return external_market_report()\n\n\n'
    )
    route_anchors = [
        '@app.get("/forward-experiments/status")\n',
        '@app.get("/post-calibration/report")\n',
        '@app.get("/binance-crosscheck/status")\n',
    ]
    for anchor in route_anchors:
        if anchor in s:
            s = s.replace(anchor, endpoints + anchor, 1)
            break
    else:
        raise RuntimeError("endpoint insertion anchor not found")

    observer_patterns = [
        r"^[ \t]+binance_crosscheck_observe\(results\)\n",
        r"^[ \t]+multihorizon_observe\(results\)\n",
    ]
    for pat in observer_patterns:
        m = re.search(pat, s, flags=re.MULTILINE)
        if m:
            indent = re.match(r"^[ \t]*", m.group(0)).group(0)
            addition = (
                f"{indent}# {API_MARKER}: Investing + macro SHADOW only; never changes action\n"
                f"{indent}external_market_observe(results)\n"
            )
            s = s[:m.end()] + addition + s[m.end():]
            break
    else:
        raise RuntimeError("observer anchor not found")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: External Market Shadow V1")


def _contains_final(node: ast.AST) -> bool:
    for x in ast.walk(node):
        if isinstance(x, ast.Constant) and isinstance(x.value, str) and "FINAL:" in x.value:
            return True
    return False


def patch_telegram(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if TG_MARKER in s:
        print("[OK] telegram_notify.py External Market lines already present")
        return

    tree = ast.parse(s)
    target_func = None
    jev_if = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _contains_final(node):
            target_func = node
            for x in ast.walk(node):
                if isinstance(x, ast.If) and isinstance(x.test, ast.Name) and x.test.id == "jev":
                    jev_if = x
                    break
            if jev_if is not None:
                break

    if target_func is None or jev_if is None:
        raise RuntimeError("Telegram formatter/JEV insertion point not found")

    lines = s.splitlines(True)
    insert_at = jev_if.lineno - 1
    indent = " " * jev_if.col_offset

    block = [
        f"{indent}# {TG_MARKER}\n",
        f"{indent}_extm = r.get(\"external_market_shadow\") or {{}}\n",
        f"{indent}if _extm:\n",
        f"{indent}    _inv = _extm.get(\"investing\") or {{}}\n",
        f"{indent}    _ifr = _inv.get(\"frames\") or {{}}\n",
        f"{indent}    if _inv:\n",
        f"{indent}        lines.append(\n",
        f"{indent}            \"INV XCHECK: \" + str(_inv.get(\"state\",\"NO_DATA\")) +\n",
        f"{indent}            \" · \" + str(_inv.get(\"alignment\",\"NO_DATA\")) +\n",
        f"{indent}            \" · 30m \" + str(_ifr.get(\"30m\",\"—\")) +\n",
        f"{indent}            \" · 1h \" + str(_ifr.get(\"1h\",\"—\")) +\n",
        f"{indent}            \" · 5h \" + str(_ifr.get(\"5h\",\"—\")) +\n",
        f"{indent}            \" · 1d \" + str(_ifr.get(\"1d\",\"—\"))\n",
        f"{indent}        )\n",
        f"{indent}    _mac = _extm.get(\"macro\") or {{}}\n",
        f"{indent}    _mch = _mac.get(\"changes_5m_pct\") or {{}}\n",
        f"{indent}    if _mac:\n",
        f"{indent}        lines.append(\n",
        f"{indent}            \"MACRO SHADOW: \" + str(_mac.get(\"state\",\"NO_DATA\")) +\n",
        f"{indent}            \" · \" + str(_mac.get(\"alignment\",\"NO_DATA\")) +\n",
        f"{indent}            \" · score \" + str(round(float(_mac.get(\"score\") or 0),2)) +\n",
        f"{indent}            \" · NDX \" + _ctx_num(_mch.get(\"NDX\")) +\n",
        f"{indent}            \" · DXY \" + _ctx_num(_mch.get(\"DXY\")) +\n",
        f"{indent}            \" · VIX \" + _ctx_num(_mch.get(\"VIX\"))\n",
        f"{indent}        )\n",
        f"{indent}    lines.append(\"EXT COMBINED: \" + str(_extm.get(\"combined_state\",\"NO_DATA\")))\n",
        "\n",
    ]
    lines[insert_at:insert_at] = block
    out = "".join(lines)
    compile(out, str(path), "exec")
    path.write_text(out, encoding="utf-8")
    print(f"[OK] telegram_notify.py patched in {target_func.name}: External Market Shadow lines")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_external_market_shadow.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")
    patch_telegram(root / "telegram_notify.py")


if __name__ == "__main__":
    main()
