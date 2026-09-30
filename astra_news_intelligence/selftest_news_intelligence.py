from __future__ import annotations
import json, os, sqlite3, tempfile, time, uuid, sys, types
from pathlib import Path

try:
    import requests  # noqa: F401
except ModuleNotFoundError:
    stub=types.ModuleType("requests")
    stub.get=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("HTTP disabled in self-test"))
    stub.post=lambda *a,**k: (_ for _ in ()).throw(RuntimeError("HTTP disabled in self-test"))
    sys.modules["requests"]=stub

def run():
    root=Path(tempfile.gettempdir())/("myshka_news_test_"+uuid.uuid4().hex)
    root.mkdir(parents=True,exist_ok=True)
    os.environ["NEWS_INTELLIGENCE_DB_PATH"]=str(root/"news.sqlite3")
    os.environ["CONTEXT_DB_PATH"]=str(root/"context.sqlite3")
    os.environ["NEWS_INTELLIGENCE_DECAY_HALF_LIFE_MIN"]="45"
    os.environ["NEWS_INTELLIGENCE_DEDUP_JACCARD"]="0.68"
    os.environ["NEWS_INTELLIGENCE_PRICED_PRE5_PCT"]="0.75"
    os.environ["NEWS_INTELLIGENCE_PRICED_PRE15_PCT"]="1.50"

    from . import news_analyzer as a
    from . import news_outcomes as o

    o.init()
    now=time.time()+1.0

    c=sqlite3.connect(os.environ["CONTEXT_DB_PATH"])
    c.execute("CREATE TABLE context_samples(id INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL,pair TEXT,source TEXT,kind TEXT,payload TEXT)")

    # Dynamic XRP universe + deterministic pre-news move:
    # 98 -> 99 -> 101 means bullish news is already priced before publication.
    for ts,price in ((now-900,98.0),(now-300,99.0),(now,101.0)):
        c.execute(
            "INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",
            (ts,"XRP/USDT:USDT","bybit","market",json.dumps({"last_price":price}))
        )

    # Same ETF story syndicated by two sources -> dedup to one logical event.
    p1={"title":"XRP ETF approval boosts demand","summary":"Institutional demand rises after an XRP ETF approval.","url":"https://source-a.test/xrp","feed":"source-a"}
    p2={"title":"XRP ETF approval boosts investor demand","summary":"An XRP ETF approval is followed by stronger investor demand.","url":"https://source-b.test/xrp","feed":"source-b"}
    c.execute("INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",(now,"*","rss","headline",json.dumps(p1)))
    c.execute("INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",(now+0.2,"*","rss","headline",json.dumps(p2)))
    c.commit(); c.close()

    a._model=lambda:("qwen-test",None)
    a._analyze=lambda item,model:a.normalize(
        {"sentiment":"BULLISH","assets":["XRP"],"confidence":0.9,"importance":0.8,
         "scope":"ASSET","event_type":"ETF","lifecycle_stage":"CONFIRMED","reason":"ETF approval supports demand"},
        item["title"]+" "+item["summary"],
        allowed_assets=a._universe_assets(now),
    )

    r=a.refresh_now()
    assert r["analyzed"]==1,r
    assert r["deduped"]==1,r
    assert "XRP" in r["universe_assets"],r

    agg=a.aggregate("XRP/USDT:USDT",now+1)
    assert agg["tone"]=="BULLISH",agg
    assert agg["event_type"]=="ETF",agg
    assert agg["lifecycle_stage"]=="CONFIRMED",agg
    assert agg["story_id"]!="UNKNOWN",agg
    assert agg["dominant_source"]!="UNKNOWN",agg
    assert float(agg["impact_score"])>0,agg
    assert agg["impact_band"] in {"LOW","MEDIUM","HIGH","EXTREME"},agg
    assert agg["surprise_state"]=="ALREADY_PRICED",agg
    assert float(agg["pre_5m_pct"])>0.75,agg
    assert float(agg["pre_15m_pct"])>1.50,agg

    fresh_weight=float(agg["effective_weight"])
    aged=a.aggregate("XRP/USDT:USDT",now+90*60)
    assert 0<float(aged["effective_weight"])<fresh_weight,(agg,aged)

    def result(price):
        return {
            "pair":"XRP/USDT:USDT","direction":"LONG","action":"DROP","reason":"selftest",
            "signal":{"direction":"LONG","structure":"UP"},
            "market":{"last_price":price},
            "edge":{"total_cost_pct":0.10},
            "binance_crosscheck":{"state":"CONFLICT","score":-0.2},
        }

    first=result(101.0)
    x=o.observe_results([first],now=now+2)
    assert x["status"]=="ok" and x["created"]==3,x
    assert first["action"]=="DROP",first
    ni=first["news_intelligence"]
    assert ni["state"]=="ALIGNED",ni
    assert ni["event_type"]=="ETF",ni
    assert ni["surprise_state"]=="ALREADY_PRICED",ni

    later=result(102.0)
    y=o.observe_results([later],now=now+302)
    assert y["closed"]>=1,y
    rep=o.report()
    h=rep["by_horizon"]["300"]
    assert h["ALIGNED"]["n"]>=1,h
    assert h["by_event_type"]["ETF"]["n"]>=1,h
    assert h["by_surprise"]["ALREADY_PRICED"]["n"]>=1,h
    assert h["news_x_binance"]["ALIGNED"]["CONFLICT"]["n"]>=1,h
    assert h["by_lifecycle"]["CONFIRMED"]["n"]>=1,h
    assert any(int(v.get("n") or 0)>=1 for v in (h["by_source"] or {}).values()),h
    assert sum(int(v.get("n") or 0) for v in (h["by_impact"] or {}).values())>=1,h
    assert "XRP/USDT:USDT" in rep["asset_lag"],rep
    assert "promotion_gate" in rep,rep

    print("NEWS_INTELLIGENCE_SELFTEST_OK")
    print("dynamic_universe=",r["universe_assets"])
    print("deduped=",r["deduped"],"analyzed=",r["analyzed"])
    print("event_type=",agg["event_type"],"lifecycle=",agg["lifecycle_stage"])
    print("story_id=",agg["story_id"],"impact=",round(float(agg["impact_score"]),2),agg["impact_band"])
    print("surprise=",agg["surprise_state"],"pre5=",round(float(agg["pre_5m_pct"]),3),"pre15=",round(float(agg["pre_15m_pct"]),3))
    print("fresh_weight=",round(fresh_weight,4),"aged_weight=",round(float(aged["effective_weight"]),4))
    print("matrix_ALIGNED_x_CONFLICT_n=",h["news_x_binance"]["ALIGNED"]["CONFLICT"]["n"])
    print("5m_aligned_avg_net=",round(h["ALIGNED"]["avg_net_pct"],4))
    print("trading_action_preserved=",first["action"])

if __name__=="__main__": run()
