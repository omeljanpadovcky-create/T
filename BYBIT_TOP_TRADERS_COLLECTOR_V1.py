#!/usr/bin/env python3
"""Windows Selenium collector for MYSHKA / ASTRA Bybit Top Traders Shadow V1.

READ-ONLY browser automation:
- opens only configured public/master-trader profile URLs;
- may click safe read-only tabs such as Trades/Positions;
- never clicks Copy, Follow, Subscribe, Buy, Sell, Open, Confirm or order controls;
- parses visible LONG/SHORT positions for configured pairs;
- pushes snapshots only to the local ASTRA bridge.

Run:
  python BYBIT_TOP_TRADERS_COLLECTOR_V1.py --config "%USERPROFILE%\\Downloads\\BYBIT_TOP_TRADERS.json"
  python BYBIT_TOP_TRADERS_COLLECTOR_V1.py --once
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any

SAFE_TAB_TEXTS = [
    "Угоди", "Trades", "Positions", "Позиції", "Current Positions",
    "Поточні позиції", "Trade History", "Історія угод",
]
BLOCKED_TEXTS = {
    "копіювати","copy","follow","підписатися","subscribe","buy","sell",
    "open long","open short","confirm","підтвердити","trade","торгувати",
}
SIDE_LONG = ("LONG","BUY LONG","OPEN LONG","ЛОНГ")
SIDE_SHORT = ("SHORT","SELL SHORT","OPEN SHORT","ШОРТ")


def load_config(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"Config not found: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def bridge_token() -> str:
    try:
        out = subprocess.check_output(
            ["docker","inspect","myshka-astra","--format","{{range .Config.Env}}{{println .}}{{end}}"],
            text=True,
            encoding="utf-8",
            errors="replace",
            stderr=subprocess.DEVNULL,
        )
        for line in out.splitlines():
            if line.startswith("MYSHKA_BRIDGE_TOKEN="):
                return line.split("=",1)[1].strip()
    except Exception:
        pass
    return ""


def post_json(url: str, token: str, payload: dict) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type":"application/json",
            "X-MYSHKA-TOKEN":token,
            "User-Agent":"MYSHKA-BybitTopTradersCollector/1.0",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return json.loads(raw) if raw else {"status":"ok"}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ASTRA HTTP {exc.code}: {raw[:500]}") from exc


def norm_pair(p: str) -> str:
    s = str(p or "").upper().strip().replace("-","/").replace("_","/")
    if ":" in s:
        s = s.split(":",1)[0]
    if "/" not in s:
        for q in ("USDT","USDC","USD"):
            if s.endswith(q) and len(s) > len(q):
                s = s[:-len(q)] + "/" + q
                break
    return s


def pair_aliases(pair: str) -> list[str]:
    p = norm_pair(pair)
    raw = p.replace("/","")
    base, quote = (p.split("/",1)+[""])[:2]
    return list(dict.fromkeys([p, raw, f"{base}-{quote}", f"{base}_{quote}"]))


def _side_from_window(window: str) -> str:
    u = window.upper()
    for tok in SIDE_LONG:
        if re.search(r"(?<![A-Z])"+re.escape(tok)+r"(?![A-Z])", u):
            return "LONG"
    for tok in SIDE_SHORT:
        if re.search(r"(?<![A-Z])"+re.escape(tok)+r"(?![A-Z])", u):
            return "SHORT"
    return ""


def parse_positions(text: str, pairs: list[str]) -> list[dict]:
    lines = [re.sub(r"\s+"," ",x).strip() for x in text.splitlines()]
    lines = [x for x in lines if x]
    out: list[dict] = []
    seen = set()

    for pair in pairs:
        p = norm_pair(pair)
        aliases = [a.upper() for a in pair_aliases(p)]
        for i, line in enumerate(lines):
            ul = line.upper()
            if not any(a and a in ul for a in aliases):
                continue
            lo, hi = max(0,i-7), min(len(lines),i+10)
            window = " | ".join(lines[lo:hi])
            side = _side_from_window(window)
            if not side:
                continue

            lev = None
            m = re.search(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[xX](?![A-Za-z])", window)
            if m:
                try: lev = float(m.group(1))
                except Exception: pass

            pnl = None
            for ln in lines[lo:hi]:
                if "PNL" in ln.upper() or "P&L" in ln.upper() or "%" in ln:
                    pm = re.search(r"([+-]?\d+(?:[.,]\d+)?)\s*%", ln)
                    if pm:
                        try: pnl = float(pm.group(1).replace(",","."))
                        except Exception: pass
                        if "PNL" in ln.upper() or "P&L" in ln.upper():
                            break

            key = (p, side)
            if key not in seen:
                seen.add(key)
                out.append({"pair":p,"side":side,"leverage":lev,"pnl_pct":pnl})
    return out


def click_safe_tabs(driver) -> None:
    from selenium.webdriver.common.by import By
    from selenium.common.exceptions import WebDriverException
    # Exact visible-text candidates only. Anything action-like is explicitly blocked.
    for label in SAFE_TAB_TEXTS:
        if label.strip().lower() in BLOCKED_TEXTS:
            continue
        xpath = (
            "//*[self::button or self::a or @role='tab']"
            "[normalize-space(text())=" + json.dumps(label) + "]"
        )
        try:
            els = driver.find_elements(By.XPATH, xpath)
            for el in els[:2]:
                try:
                    if el.is_displayed() and el.is_enabled():
                        txt = (el.text or "").strip().lower()
                        if txt and txt not in BLOCKED_TEXTS:
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
                            el.click()
                            time.sleep(1.2)
                            return
                except WebDriverException:
                    pass
        except WebDriverException:
            pass


def make_driver(cfg: dict):
    try:
        from selenium import webdriver
    except ImportError:
        raise SystemExit("Selenium not installed. Run: python -m pip install --user selenium")

    browser = str(cfg.get("browser") or "edge").lower()
    profile_dir = Path(os.path.expandvars(os.path.expanduser(
        cfg.get("profile_dir") or "~/.myshka/bybit-toptraders-browser"
    ))).resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    if browser == "chrome":
        from selenium.webdriver.chrome.options import Options
        opts = Options()
        opts.add_argument(f"--user-data-dir={profile_dir}")
        opts.add_argument("--disable-notifications")
        opts.add_argument("--start-maximized")
        if cfg.get("headless"):
            opts.add_argument("--headless=new")
        return webdriver.Chrome(options=opts)

    from selenium.webdriver.edge.options import Options
    opts = Options()
    opts.add_argument(f"--user-data-dir={profile_dir}")
    opts.add_argument("--disable-notifications")
    opts.add_argument("--start-maximized")
    if cfg.get("headless"):
        opts.add_argument("--headless=new")
    return webdriver.Edge(options=opts)


def scrape_one(driver, trader: dict, pairs: list[str], wait_sec: float) -> dict:
    url = str(trader.get("url") or "").strip()
    name = str(trader.get("name") or trader.get("id") or url)
    tid = str(trader.get("id") or hashlib.sha256(url.encode("utf-8")).hexdigest()[:16])
    if not url.lower().startswith(("https://www.bybit.com/","https://bybit.com/")):
        return {
            "trader_id":tid,"trader_name":name,"source_url":url,
            "observed_at":time.time(),"status":"blocked_non_bybit_url","positions":[],
        }

    driver.get(url)
    time.sleep(wait_sec)
    click_safe_tabs(driver)
    time.sleep(1.0)

    body = driver.find_element("tag name","body").text
    positions = parse_positions(body, pairs)
    digest = hashlib.sha256(body.encode("utf-8",errors="ignore")).hexdigest()[:16]
    return {
        "trader_id":tid,
        "trader_name":name,
        "source_url":url,
        "observed_at":time.time(),
        "status":"ok" if positions else "no_positions_or_unrecognized",
        "positions":positions,
        "page_text_sha16":digest,
        "body_chars":len(body),
        "collector":"selenium_read_only_v1",
    }


def run_cycle(driver, cfg: dict, token: str) -> list[dict]:
    bridge = str(cfg.get("bridge_url") or "http://127.0.0.1:8088").rstrip("/")
    pairs = [norm_pair(x) for x in (cfg.get("pairs") or ["BTC/USDT","ETH/USDT","SOL/USDT"])]
    traders = [x for x in (cfg.get("traders") or []) if isinstance(x,dict)]
    wait_sec = max(1.5,float(cfg.get("page_wait_sec") or 4.0))
    rows = []
    if not traders:
        print("[WARN] No trader URLs configured.")
        return rows

    for trader in traders:
        try:
            snap = scrape_one(driver,trader,pairs,wait_sec)
            result = post_json(bridge+"/bybit-top-traders/push",token,snap)
            print(
                f"[{snap['trader_name']}] status={snap['status']} "
                f"positions={len(snap['positions'])} push={result.get('status')}"
            )
            for p in snap["positions"]:
                print(f"  {p['pair']} {p['side']} lev={p.get('leverage')} pnl={p.get('pnl_pct')}")
            rows.append(snap)
        except Exception as exc:
            print(f"[ERROR] {trader.get('name') or trader.get('url')}: {type(exc).__name__}: {exc}")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path.home()/"Downloads"/"BYBIT_TOP_TRADERS.json"))
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    cfg = load_config(Path(args.config))
    token = str(cfg.get("bridge_token") or "").strip() or bridge_token()
    if not token:
        raise SystemExit("MYSHKA bridge token not found. Keep myshka-astra running.")

    driver = make_driver(cfg)
    interval = max(30,int(cfg.get("interval_sec") or 60))
    try:
        while True:
            run_cycle(driver,cfg,token)
            if args.once:
                break
            time.sleep(interval)
    finally:
        driver.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
