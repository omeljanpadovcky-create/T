from pathlib import Path
import sys

MARKER = "MYSHKA_STRICT_EDGE_PAYLOAD_V2"

OLD = '''    if strict_4of4 and edge is not None and edge.net_edge_pct <= 0.05:
        training_meta["strict_edge_min_pct"] = 0.05
        return {
            "action": "DROP", "reason": "strict_edge_buffer", "pair": req.pair,
            "signal": _clean(sig.as_dict()), "edge": _clean(edge.as_dict()),
            "training": training_meta,
        }
'''

NEW = '''    if strict_4of4 and edge is not None and edge.net_edge_pct <= 0.05:
        # MYSHKA_STRICT_EDGE_PAYLOAD_V2
        edge_payload = _clean(edge.as_dict())
        if not isinstance(edge_payload, dict):
            edge_payload = {}
        edge_payload["passed"] = False
        edge_payload["reason"] = "strict_edge_buffer"
        edge_payload["min_required_net_edge_pct"] = 0.05
        training_meta["strict_edge_min_pct"] = 0.05
        return {
            "action": "DROP", "reason": "strict_edge_buffer", "pair": req.pair,
            "signal": _clean(sig.as_dict()), "edge": edge_payload,
            "training": training_meta,
        }
'''


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_strict_edge_server_v2.py <api.py>")
    path = Path(sys.argv[1]).resolve()
    src = path.read_text(encoding="utf-8-sig")
    compile(src, str(path), "exec")

    if MARKER in src:
        print("[OK] STRICT EDGE server payload V2 already present")
        return

    if OLD not in src:
        raise RuntimeError(
            "Expected STRICT EDGE +0.05 block not found. "
            "Aborting without changing api.py."
        )

    src = src.replace(OLD, NEW, 1)
    compile(src, str(path), "exec")
    path.write_text(src, encoding="utf-8")
    print("[OK] STRICT EDGE server payload now returns passed=false on strict buffer DROP")
    print("[OK] reason=strict_edge_buffer")
    print("[OK] min_required_net_edge_pct=0.05")


if __name__ == "__main__":
    main()
