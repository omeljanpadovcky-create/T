from pathlib import Path
import importlib
import os
import tempfile
import time
import uuid


def run():
    root = Path(tempfile.gettempdir()) / ("myshka_hardening_test_" + uuid.uuid4().hex)
    root.mkdir(parents=True, exist_ok=True)
    os.environ["HARDENING_DB_PATH"] = str(root / "hardening.sqlite3")
    os.environ["ANALYTICS_DB_PATH"] = str(root / "analytics.sqlite3")

    import system_hardening as h
    importlib.reload(h)

    t0 = time.perf_counter()
    a = h.init()
    b = h.status()
    c = h.report(
        engine={"paper_equity": 1000.0, "positions": []},
        runtime={"kill_switch": False, "paused": False, "auto_scan": True},
        integrations=None,
        do_reconcile=False,
    )
    elapsed = time.perf_counter() - t0

    assert a.get("status") == "ok", a
    assert b.get("enabled") is True and not b.get("error"), b
    assert c.get("status") == "ok", c
    assert elapsed < 3.0, f"hardening calls too slow: {elapsed:.3f}s"

    print("HARDENING_RECURSION_SELFTEST_OK")
    print("elapsed_sec=", round(elapsed, 4))
    print("status=", b)
    print("report_mode=", c.get("mode"))


if __name__ == "__main__":
    run()
