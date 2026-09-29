from pathlib import Path
import sys

MD_MARKER = 'MYSHKA_BYBIT_RATE_GUARD_V1'
API_MARKER = 'MYSHKA_ENGINE_SCAN_GUARD_V1'


def replace_once(s: str, old: str, new: str, label: str) -> str:
    if old not in s:
        raise RuntimeError(f'patch target not found: {label}')
    return s.replace(old, new, 1)


def replace_function(s: str, name: str, new_text: str) -> str:
    start = s.find(f'def {name}(')
    if start < 0:
        raise RuntimeError(f'function not found: {name}')
    nxt = s.find('\ndef ', start + 5)
    if nxt < 0:
        raise RuntimeError(f'next function after {name} not found')
    return s[:start] + new_text.rstrip() + '\n\n' + s[nxt + 1:]


def patch_market_data(path: Path) -> None:
    s = path.read_text(encoding='utf-8-sig')
    if MD_MARKER in s:
        print('[OK] market_data.py already has rate/cache guard')
        return

    s = replace_once(s, 'import os\nimport time\nfrom typing import List\n',
                     'import os\nimport time\nimport threading\nfrom typing import List\n', 'threading import')

    insert = f'''# {MD_MARKER}\n_PUBLIC_REQUEST_LOCK = threading.Lock()\n_LAST_PUBLIC_REQUEST_AT = 0.0\n_PUBLIC_MIN_GAP_SEC = max(0.02, float(os.getenv("BYBIT_PUBLIC_MIN_GAP_SEC", "0.10")))\n_PUBLIC_MAX_RETRIES = max(1, min(6, int(os.getenv("BYBIT_PUBLIC_MAX_RETRIES", "4"))))\n_PUBLIC_BACKOFF_SEC = max(0.2, float(os.getenv("BYBIT_PUBLIC_BACKOFF_SEC", "1.0")))\n_KLINE_CACHE_LOCK = threading.RLock()\n_KLINE_CACHE: dict[str, dict] = {{}}\n\n'''
    s = replace_once(s, 'class MarketDataError(RuntimeError):\n', insert + 'class MarketDataError(RuntimeError):\n', 'guard globals')

    new_get = '''def _get(path: str, params: dict) -> dict:\n    global _LAST_PUBLIC_REQUEST_AT\n    url = f"{BYBIT_PUBLIC_BASE_URL}{path}"\n    last_exc = None\n    for attempt in range(_PUBLIC_MAX_RETRIES):\n        with _PUBLIC_REQUEST_LOCK:\n            now_mono = time.monotonic()\n            wait = _PUBLIC_MIN_GAP_SEC - (now_mono - _LAST_PUBLIC_REQUEST_AT)\n            if wait > 0:\n                time.sleep(wait)\n            _LAST_PUBLIC_REQUEST_AT = time.monotonic()\n        try:\n            r = requests.get(url, params=params, timeout=HTTP_TIMEOUT_SEC)\n            try:\n                data = r.json()\n            except Exception:\n                data = {}\n\n            ret_code = data.get("retCode")\n            ret_msg = str(data.get("retMsg") or "")\n            rate_limited = (\n                r.status_code == 429\n                or ret_code == 10006\n                or "too many visits" in ret_msg.lower()\n                or "rate limit" in ret_msg.lower()\n            )\n            if rate_limited:\n                if attempt + 1 < _PUBLIC_MAX_RETRIES:\n                    retry_after = r.headers.get("Retry-After")\n                    try:\n                        delay = max(_PUBLIC_BACKOFF_SEC * (2 ** attempt), float(retry_after or 0))\n                    except Exception:\n                        delay = _PUBLIC_BACKOFF_SEC * (2 ** attempt)\n                    time.sleep(min(delay, 8.0))\n                    continue\n                raise MarketDataError(f"Bybit rate limit for {path}: {ret_code or r.status_code} {ret_msg}")\n\n            r.raise_for_status()\n            if ret_code != 0:\n                raise MarketDataError(f"Bybit error {ret_code}: {ret_msg}")\n            return data\n        except MarketDataError:\n            raise\n        except Exception as exc:\n            last_exc = exc\n            if attempt + 1 < _PUBLIC_MAX_RETRIES:\n                time.sleep(min(_PUBLIC_BACKOFF_SEC * (2 ** attempt), 8.0))\n                continue\n    raise MarketDataError(f"Bybit request failed for {path}: {type(last_exc).__name__}: {last_exc}") from last_exc'''
    s = replace_function(s, '_get', new_get)

    helper = '''def _fetch_closed_candles(pair: str) -> list[dict]:\n    symbol = _symbol_from_pair(pair)\n    now = time.time()\n    minute_bucket = int(now // 60)\n    with _KLINE_CACHE_LOCK:\n        cached = _KLINE_CACHE.get(symbol)\n        if cached and int(cached.get("minute_bucket", -1)) == minute_bucket:\n            return [dict(x) for x in cached.get("candles", [])]\n        if cached and (now % 60) < 3.0:\n            return [dict(x) for x in cached.get("candles", [])]\n\n        raw = _get(\n            "/v5/market/kline",\n            {\n                "category": "linear",\n                "symbol": symbol,\n                "interval": "1",\n                "limit": CONFIG.CANDLE_LIMIT + 1,\n            },\n        )\n        rows = raw.get("result", {}).get("list", [])\n        if len(rows) < CONFIG.CANDLE_LIMIT:\n            raise MarketDataError(f"{symbol}: only {len(rows)} klines returned, need {CONFIG.CANDLE_LIMIT}")\n        rows = list(reversed(rows))\n        rows = rows[:-1][-CONFIG.CANDLE_LIMIT:]\n        candles = [\n            {"open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}\n            for r in rows\n        ]\n        _KLINE_CACHE[symbol] = {"minute_bucket": minute_bucket, "fetched_at": now, "candles": candles}\n        return [dict(x) for x in candles]\n\n\n'''
    s = replace_once(s, 'def fetch_pair_market(pair: str, ticker: dict | None = None) -> dict:\n',
                     helper + 'def fetch_pair_market(pair: str, ticker: dict | None = None) -> dict:\n', 'candle cache helper')

    old_block = '''    raw = _get(\n        "/v5/market/kline",\n        {\n            "category": "linear",\n            "symbol": symbol,\n            "interval": "1",\n            "limit": CONFIG.CANDLE_LIMIT + 1,\n        },\n    )\n    rows = raw.get("result", {}).get("list", [])\n    if len(rows) < CONFIG.CANDLE_LIMIT:\n        raise MarketDataError(f"{symbol}: only {len(rows)} klines returned, need {CONFIG.CANDLE_LIMIT}")\n\n    rows = list(reversed(rows))\n    rows = rows[:-1][-CONFIG.CANDLE_LIMIT:]\n\n    candles = [\n        {"open": float(r[1]), "high": float(r[2]), "low": float(r[3]), "close": float(r[4]), "volume": float(r[5])}\n        for r in rows\n    ]\n    df = pd.DataFrame(candles)\n'''
    new_block = '''    candles = _fetch_closed_candles(pair)\n    if len(candles) < CONFIG.CANDLE_LIMIT:\n        raise MarketDataError(f"{symbol}: candle cache has only {len(candles)} rows")\n    df = pd.DataFrame(candles)\n'''
    s = replace_once(s, old_block, new_block, 'fetch_pair_market kline block')

    path.write_text(s, encoding='utf-8')
    print('[OK] market_data.py: 1m kline cache + request pacing + 10006/429 backoff')


def patch_api(path: Path) -> None:
    s = path.read_text(encoding='utf-8-sig')
    if API_MARKER in s:
        print('[OK] api.py already has scan/stale-settlement guard')
        return

    s = replace_once(s, '_PHONE_LOCK = threading.RLock()\n',
                     f'_PHONE_LOCK = threading.RLock()\n# {API_MARKER}\n_ENGINE_STEP_LOCK = threading.Lock()\n_MAX_SETTLE_DELAY_SEC = max(30, int(os.getenv("MYSHKA_MAX_SETTLE_DELAY_SEC", "90")))\n',
                     'engine locks')

    s = replace_once(s, 'def _engine_step(force: bool = False) -> dict:\n',
                     'def _engine_step_unlocked(force: bool = False) -> dict:\n', 'rename engine step')
    wrapper = '''def _engine_step(force: bool = False) -> dict:\n    if not _ENGINE_STEP_LOCK.acquire(blocking=False):\n        return {"status": "busy", "reason": "scan already running", "engine": phone_engine_status(), "results": _PHONE_LATEST_RESULTS}\n    try:\n        return _engine_step_unlocked(force)\n    finally:\n        _ENGINE_STEP_LOCK.release()\n\n\n'''
    s = replace_once(s, 'def _engine_loop():\n', wrapper + 'def _engine_loop():\n', 'engine step wrapper')

    start = s.find('def _engine_settle_from_results(results: list[dict]) -> list[dict]:')
    end = s.find('\ndef _engine_open_from_results', start)
    if start < 0 or end < 0:
        raise RuntimeError('settle function boundaries not found')
    new_settle = '''def _engine_settle_from_results(results: list[dict]) -> list[dict]:\n    by_pair = {r.get("pair"): r for r in results if r.get("pair")}\n    now = time.time()\n    closed = []\n    stale = []\n    with _PHONE_LOCK:\n        for pair, p in list(_PHONE.get("positions", {}).items()):\n            target = float(p.get("opened_at", now)) + int(p.get("horizon_sec", 300))\n            if now < target:\n                continue\n            settle_delay = max(0.0, now - target)\n            if settle_delay > _MAX_SETTLE_DELAY_SEC:\n                stale.append({\n                    "pair": pair, "side": p.get("side"),\n                    "delay_sec": round(settle_delay, 1),\n                    "horizon_sec": int(p.get("horizon_sec", 300)),\n                })\n                del _PHONE["positions"][pair]\n                continue\n\n            r = by_pair.get(pair)\n            market = (r or {}).get("market") or {}\n            last = float(market.get("last_price") or 0.0)\n            if last <= 0:\n                continue\n            entry = float(p["entry"])\n            raw = (last - entry) / entry * 100.0\n            gross = raw if p["side"] == "LONG" else -raw\n            costs = float(p.get("costs_pct", 0.0))\n            net = gross - costs\n            hit = gross > 0\n            notional_pct = float(p.get("notional_pct_equity", 0.0))\n            pnl_amount = float(_PHONE["paper_equity"]) * (notional_pct / 100.0) * (net / 100.0)\n            _PHONE["paper_equity"] = float(_PHONE["paper_equity"]) + pnl_amount\n            rec = TradeRecord(\n                pair=pair, side=p["side"], regime=p.get("regime", "RANGE"),\n                horizon_sec=int(p.get("horizon_sec", 300)), direction_hit=hit,\n                gross_return_pct=gross, net_return_pct=net, mfe_pct=0.0, mae_pct=0.0,\n                expected_edge_pct=float(p.get("expected_edge_pct", 0.0)),\n                realized_edge_pct=net - float(p.get("expected_edge_pct", 0.0)),\n                entered_at=float(p.get("opened_at", now)),\n            )\n            trade_id = log_trade(rec)\n            closed.append({"trade_id": trade_id, "pair": pair, "side": p["side"], "gross_pct": gross, "net_pct": net, "direction_hit": hit})\n            del _PHONE["positions"][pair]\n        _phone_save()\n\n    for x in stale:\n        _emit_event({"event": "SETTLE_SKIPPED", "source": "phone-engine", **x})\n        if runtime_get().get("telegram_notifications_enabled", True):\n            try:\n                telegram_send(\n                    f"*PHONE ENGINE STALE SETTLE SKIPPED* {x['pair']} {x['side']}\\n"\n                    f"delay: {x['delay_sec']:.0f}s > max {_MAX_SETTLE_DELAY_SEC}s\\n"\n                    "Excluded from learner / P&L because the 5m horizon was missed."\n                )\n            except Exception:\n                pass\n\n    for c in closed:\n        event = {"event": "REVIEW", "source": "phone-engine", **c}\n        _emit_event(event)\n        if runtime_get().get("telegram_notifications_enabled", True):\n            try:\n                telegram_send(\n                    f"*PHONE ENGINE REVIEW* {c['pair']} {c['side']}\\n"\n                    f"gross: {c['gross_pct']:.3f}%\\nnet: {c['net_pct']:.3f}%\\n"\n                    f"direction: {'HIT' if c['direction_hit'] else 'MISS'}"\n                )\n            except Exception:\n                pass\n    return closed\n'''
    s = s[:start] + new_settle + s[end:]

    path.write_text(s, encoding='utf-8')
    print('[OK] api.py: serialized scans + stale 5m settlement guard')


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit('usage: patch_rate_limit_guard.py <ASTRA_PROJECT_DIR>')
    root = Path(sys.argv[1]).resolve()
    patch_market_data(root / 'market_data.py')
    patch_api(root / 'api.py')


if __name__ == '__main__':
    main()
