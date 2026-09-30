from pathlib import Path
import re
import sys

MARKER = "MYSHKA_EXTERNAL_MARKET_XCHECK_V1"
TG_MARKER = "MYSHKA_EXTERNAL_MARKET_XCHECK_TG_V1"


def _insert_after_line(s: str, pattern: str, addition: str, label: str) -> str:
    m = re.search(pattern, s, flags=re.MULTILINE)
    if not m:
        raise RuntimeError(f"{label} not found")
    return s[:m.end()] + addition + s[m.end():]


def patch_api(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if MARKER in s:
        print("[OK] api.py external xcheck already present")
        return

    import_line = (
        "from .external_market_xcheck import init as external_xcheck_init, "
        "status as external_xcheck_status, report as external_xcheck_report, "
        "observe_results as external_xcheck_observe\n"
    )

    if re.search(r"^from \.binance_signal_crosscheck import .+$", s, flags=re.MULTILINE):
        s = _insert_after_line(
            s, r"^from \.binance_signal_crosscheck import .+\n",
            import_line, "Binance xcheck import"
        )
    elif re.search(r"^from \.multihorizon_shadow import .+$", s, flags=re.MULTILINE):
        s = _insert_after_line(
            s, r"^from \.multihorizon_shadow import .+\n",
            import_line, "Multi-Horizon import"
        )
    else:
        raise RuntimeError("observer import insertion point not found")

    if re.search(r"^[ \t]+binance_crosscheck_init\(\)\n", s, flags=re.MULTILINE):
        s = _insert_after_line(
            s, r"^[ \t]+binance_crosscheck_init\(\)\n",
            f"    # {MARKER}\n    external_xcheck_init()\n",
            "Binance startup"
        )
    elif re.search(r"^[ \t]+multihorizon_init\(\)\n", s, flags=re.MULTILINE):
        s = _insert_after_line(
            s, r"^[ \t]+multihorizon_init\(\)\n",
            f"    # {MARKER}\n    external_xcheck_init()\n",
            "Multi-Horizon startup"
        )
    else:
        raise RuntimeError("startup insertion point not found")

    if re.search(r'^[ \t]+"binance_crosscheck":\s*binance_crosscheck_status\(\),\n', s, flags=re.MULTILINE):
        s = _insert_after_line(
            s, r'^[ \t]+"binance_crosscheck":\s*binance_crosscheck_status\(\),\n',
            f'        # {MARKER}\n        "external_market_xcheck": external_xcheck_status(),\n',
            "Binance health"
        )
    elif re.search(r'^[ \t]+"multihorizon_shadow":\s*multihorizon_status\(\),\n', s, flags=re.MULTILINE):
        s = _insert_after_line(
            s, r'^[ \t]+"multihorizon_shadow":\s*multihorizon_status\(\),\n',
            f'        # {MARKER}\n        "external_market_xcheck": external_xcheck_status(),\n',
            "Multi-Horizon health"
        )
    else:
        raise RuntimeError("health insertion point not found")

    endpoints = (
        f'# {MARKER}\n'
        '@app.get("/external-xcheck/status")\n'
        'def external_xcheck_status_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return external_xcheck_status()\n\n\n'
        '@app.get("/external-xcheck/report")\n'
        'def external_xcheck_report_api(x_myshka_token: Optional[str] = Header(default=None)):\n'
        '    _require_token(x_myshka_token)\n'
        '    return external_xcheck_report()\n\n\n'
    )
    route_candidates = [
        '@app.get("/forward-experiment/report")\n',
        '@app.get("/binance-crosscheck/status")\n',
        '@app.get("/multihorizon/report")\n',
    ]
    for route in route_candidates:
        if route in s:
            s = s.replace(route, endpoints + route, 1)
            break
    else:
        raise RuntimeError("endpoint insertion point not found")

    if re.search(r"^[ \t]+forward_experiment_observe\(results\)\n", s, flags=re.MULTILINE):
        m = re.search(r"^[ \t]+forward_experiment_observe\(results\)\n", s, flags=re.MULTILINE)
        indent = re.match(r"[ \t]*", m.group(0)).group(0)
        add = (
            f"{indent}# {MARKER}: SHADOW only; never changes action\n"
            f"{indent}external_xcheck_observe(results)\n"
        )
        s = s[:m.start()] + add + s[m.start():]
    elif re.search(r"^[ \t]+binance_crosscheck_observe\(results\)\n", s, flags=re.MULTILINE):
        s = _insert_after_line(
            s, r"^[ \t]+binance_crosscheck_observe\(results\)\n",
            f"        # {MARKER}: SHADOW only; never changes action\n"
            "        external_xcheck_observe(results)\n",
            "Binance observer"
        )
    else:
        raise RuntimeError("observer insertion point not found")

    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched: External Market XCheck V1")


def patch_telegram(path: Path) -> None:
    s = path.read_text(encoding="utf-8-sig")
    compile(s, str(path), "exec")
    if TG_MARKER in s:
        print("[OK] telegram_notify.py external xcheck already present")
        return

    pat = r'(?m)^(?P<indent>[ \t]+)guard_reasons = r\.get\("guard_reasons"\) or \[\]\s*$'
    m = re.search(pat, s)
    if not m:
        raise RuntimeError("telegram guard anchor not found")
    indent = m.group("indent")

    block = (
        f'{indent}# {TG_MARKER}\n'
        f'{indent}_ix = r.get("investing_xcheck") or {{}}\n'
        f'{indent}if _ix:\n'
        f'{indent}    _ix_r = _ix.get("ratings") or {{}}\n'
        f'{indent}    _ix_bits = []\n'
        f'{indent}    for _k in ("30m","1h","5h","1d"):\n'
        f'{indent}        if _ix_r.get(_k):\n'
        f'{indent}            _ix_bits.append(f"{{_k}}={{_ix_r.get(_k)}}")\n'
        f'{indent}    _ix_tail = (" · " + " · ".join(_ix_bits)) if _ix_bits else ""\n'
        f'{indent}    lines.append(f"INVESTING XCHECK: {{_ix.get(\'state\',\'NO_DATA\')}} · dir {{_ix.get(\'direction\',\'NO_DATA\')}}{{_ix_tail}}")\n'
        f'{indent}_mx = r.get("macro_crossmarket") or {{}}\n'
        f'{indent}if _mx:\n'
        f'{indent}    _assets = _mx.get("assets") or {{}}\n'
        f'{indent}    _mbits = []\n'
        f'{indent}    for _name in ("NASDAQ100","DXY","GOLD","WTI","VIX"):\n'
        f'{indent}        _row = _assets.get(_name) or {{}}\n'
        f'{indent}        _chg = _row.get("change_5m_pct")\n'
        f'{indent}        if _chg is not None:\n'
        f'{indent}            try:\n'
        f'{indent}                _mbits.append(f"{{_name}} {{float(_chg):+.2f}}%")\n'
        f'{indent}            except Exception:\n'
        f'{indent}                pass\n'
        f'{indent}    _mtail = (" · " + " · ".join(_mbits)) if _mbits else ""\n'
        f'{indent}    lines.append(f"MACRO SHADOW: {{_mx.get(\'state\',\'NO_DATA\')}} · {{_mx.get(\'regime\',\'NO_DATA\')}}{{_mtail}}")\n'
        '\n'
    )

    s = s[:m.start()] + block + s[m.start():]
    compile(s, str(path), "exec")
    path.write_text(s, encoding="utf-8")
    print("[OK] telegram_notify.py patched: external xcheck lines")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_external_market_xcheck.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")
    tg = root / "telegram_notify.py"
    if tg.exists():
        patch_telegram(tg)
    else:
        print("[WARN] telegram_notify.py not found; API module still installed")


if __name__ == "__main__":
    main()
