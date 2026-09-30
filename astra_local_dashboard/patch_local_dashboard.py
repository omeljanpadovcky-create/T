from pathlib import Path
import re
import sys

MARKER = "MYSHKA_LOCAL_DASHBOARD_V1"


def patch_api(api_path: Path) -> None:
    s = api_path.read_text(encoding="utf-8-sig")
    compile(s, str(api_path), "exec")
    if MARKER in s:
        old = (
            "def myshka_local_dashboard():\n"
            "    p = _MyshkaDashboardPath(__file__).resolve().parent / 'index.html'\n"
            "    return _MyshkaDashboardFileResponse(str(p), media_type='text/html', headers={'X-MYSHKA-Dashboard':'1','Cache-Control':'no-store'})\n"
        )
        new = (
            "def myshka_local_dashboard():\n"
            "    data_p = _MyshkaDashboardPath('/data/myshka_dashboard.html')\n"
            "    app_p = _MyshkaDashboardPath(__file__).resolve().parent / 'index.html'\n"
            "    p = data_p if data_p.exists() else app_p\n"
            "    return _MyshkaDashboardFileResponse(str(p), media_type='text/html')\n"
        )
        if old in s:
            s = s.replace(old, new, 1)
            compile(s, str(api_path), "exec")
            api_path.write_text(s, encoding="utf-8")
            print("[OK] Existing local dashboard route upgraded to /data fallback")
            return
        if "/data/myshka_dashboard.html" in s and "X-MYSHKA-Dashboard" in s:
            print("[OK] Local dashboard route already upgraded")
            return
        if "/data/myshka_dashboard.html" in s and "X-MYSHKA-Dashboard" not in s:
            old_return = "    return _MyshkaDashboardFileResponse(str(p), media_type='text/html')\n"
            new_return = "    return _MyshkaDashboardFileResponse(str(p), media_type='text/html', headers={'X-MYSHKA-Dashboard':'1','Cache-Control':'no-store'})\n"
            if old_return not in s:
                raise RuntimeError("Upgraded dashboard route found but FileResponse shape is unknown")
            s = s.replace(old_return, new_return, 1)
            compile(s, str(api_path), "exec")
            api_path.write_text(s, encoding="utf-8")
            print("[OK] Existing local dashboard route upgraded with verification header")
            return
        raise RuntimeError("Local dashboard marker exists but route shape is unknown")

    # Add isolated imports after the module docstring AND any __future__
    # imports (Python requires future imports to remain first).
    insert_at = 0
    if s.startswith("#!"):
        nl = s.find("\n")
        insert_at = (nl + 1) if nl >= 0 else len(s)

    tail = s[insert_at:]
    if tail.startswith('"""') or tail.startswith("'''"):
        quote = tail[:3]
        end = tail.find(quote, 3)
        if end >= 0:
            nl = tail.find("\n", end + 3)
            insert_at += (nl + 1) if nl >= 0 else (end + 3)

    future_re = re.compile(r"^from __future__ import .+\n", re.MULTILINE)
    while True:
        m_future = future_re.match(s, insert_at)
        if not m_future:
            break
        insert_at = m_future.end()

    imports = (
        "from pathlib import Path as _MyshkaDashboardPath\n"
        "from fastapi.responses import FileResponse as _MyshkaDashboardFileResponse\n"
    )
    s = s[:insert_at] + imports + s[insert_at:]

    # Insert route after FastAPI app creation.
    m = re.search(r"^app\s*=\s*FastAPI\([^\n]*\)\s*$", s, flags=re.MULTILINE)
    if not m:
        # tolerate multiline FastAPI(...) initialization: insert before first decorator
        first_route = re.search(r"^@app\.", s, flags=re.MULTILINE)
        if not first_route:
            raise RuntimeError("FastAPI app insertion point not found")
        pos = first_route.start()
    else:
        pos = m.end()

    route = (
        "\n\n# " + MARKER + "\n"
        "@app.get('/dashboard', include_in_schema=False)\n"
        "def myshka_local_dashboard():\n"
        "    data_p = _MyshkaDashboardPath('/data/myshka_dashboard.html')\n"
        "    app_p = _MyshkaDashboardPath(__file__).resolve().parent / 'index.html'\n"
        "    p = data_p if data_p.exists() else app_p\n"
        "    return _MyshkaDashboardFileResponse(str(p), media_type='text/html', headers={'X-MYSHKA-Dashboard':'1','Cache-Control':'no-store'})\n\n"
        "@app.get('/ui', include_in_schema=False)\n"
        "def myshka_local_ui_alias():\n"
        "    return myshka_local_dashboard()\n"
    )
    s = s[:pos] + route + s[pos:]

    compile(s, str(api_path), "exec")
    api_path.write_text(s, encoding="utf-8")
    print("[OK] api.py patched with /dashboard and /ui")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_local_dashboard.py <ASTRA_PROJECT_DIR>")
    root = Path(sys.argv[1]).resolve()
    patch_api(root / "api.py")


if __name__ == "__main__":
    main()
