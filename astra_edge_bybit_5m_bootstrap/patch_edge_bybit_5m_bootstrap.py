#!/usr/bin/env python3
"""Patch MYSHKA/ASTRA edge.py cold-start expected-move logic.

V1 goal:
- keep the existing EDGE cost model and pass rule untouched;
- for a 5m horizon, prefer already-collected pooled horizon samples when the
  pair/side/regime bucket is still cold;
- fall back to ATR*0.5 only when pooled support is also insufficient.

This patch is intentionally narrow and does not enable live execution.
"""
from __future__ import annotations

import ast
from pathlib import Path
import sys

NEW_FUNC = '''def estimate_expected_move(
    bucket_samples: Sequence[float],
    pooled_samples: Sequence[float],
    atr_pct_bootstrap: float,
) -> tuple:
    """Returns (expected_move_pct, basis, n_samples_in_bucket).

    Cold-start V1:
    - bucket >= full support: bucket quantile;
    - bucket warming: shrink bucket toward pooled 5m quantile;
    - bucket cold: use pooled 5m quantile when pooled support is sufficient;
    - only if both bucket and pooled are cold, use ATR bootstrap.
    """
    n = len(bucket_samples)
    pooled_n = len(pooled_samples)

    pooled_q = (
        float(np.quantile(pooled_samples, CONFIG.EXPECTED_MOVE_QUANTILE))
        if pooled_n >= CONFIG.MIN_SAMPLES_SOFT
        else None
    )

    if n < CONFIG.MIN_SAMPLES_SOFT:
        if pooled_q is not None:
            return pooled_q, "pooled_5m", n
        return atr_pct_bootstrap, "bootstrap_atr", n

    bucket_q = float(np.quantile(bucket_samples, CONFIG.EXPECTED_MOVE_QUANTILE))

    if n >= CONFIG.MIN_SAMPLES_FULL:
        return bucket_q, "bucket", n

    fallback = pooled_q if pooled_q is not None else atr_pct_bootstrap
    weight = (n - CONFIG.MIN_SAMPLES_SOFT) / (CONFIG.MIN_SAMPLES_FULL - CONFIG.MIN_SAMPLES_SOFT)
    shrunk = weight * bucket_q + (1 - weight) * fallback
    return shrunk, "shrunk_bucket", n
'''

def patch(path: Path) -> None:
    src = path.read_text(encoding="utf-8-sig").lstrip("\ufeff")
    if '"pooled_5m"' in src and "Cold-start V1" in src:
        print("already_patched")
        return

    tree = ast.parse(src)
    target = None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "estimate_expected_move":
            target = node
            break
    if target is None or not getattr(target, "end_lineno", None):
        raise SystemExit("estimate_expected_move function not found")

    old = "\n".join(src.splitlines()[target.lineno - 1: target.end_lineno])
    required = [
        "atr_pct_bootstrap",
        "CONFIG.MIN_SAMPLES_SOFT",
        "CONFIG.MIN_SAMPLES_FULL",
        "CONFIG.EXPECTED_MOVE_QUANTILE",
    ]
    for marker in required:
        if marker not in old:
            raise SystemExit(f"unexpected estimate_expected_move implementation; missing {marker}")

    lines = src.splitlines(keepends=True)
    replacement = NEW_FUNC.rstrip() + "\n"
    new_src = "".join(lines[: target.lineno - 1]) + replacement + "".join(lines[target.end_lineno:])
    ast.parse(new_src)
    path.write_text(new_src, encoding="utf-8")
    print("patched")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_edge_bybit_5m_bootstrap.py <edge.py>")
    patch(Path(sys.argv[1]).resolve())
