from pathlib import Path
import re
import sys

MARKER = "MYSHKA_LOCAL_DASHBOARD_V1"


def patch_api(api_path: Path) -> None:
    s = api_path.read_text(encoding="utf-8-sig")
    compile(s, str(api_path), "exec")
    if MARKER in s:
        print("[OK] Local dashboard route already present")
        return

    # Add isolated imports that cannot clash with existing names.
    insert_at = 0
    lines = s.splitlines(True)
    if lines and lines[0].startswith("#!"):
        insert_at = len(lines[0])
    if s.startswith('"""') or s.startswith("'''"):
        quote = s[:3]
        end = s.find(quote, 3)
        if end >= 0:
            nl = s.find("\n", end + 3)
            insert_at = (nl + 1) if nl >= 0 else (end + 3)

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
        "    p = _MyshkaDashboardPath(__file__).resolve().parent / 'index.html'\n"
        "    return _MyshkaDashboardFileResponse(str(p), media_type='text/html')\n\n"
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
