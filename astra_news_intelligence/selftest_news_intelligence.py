from __future__ import annotations
import json, os, sqlite3, tempfile, time, uuid, sys, types
from pathlib import Path

# Synthetic self-test performs no real HTTP. Windows host Python may not have
# requests even though Docker does, so provide an import stub when needed.
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

    from . import news_analyzer as a
    from . import news_outcomes as o

    # Create outcome meta first so all synthetic events are definitely forward.
    o.init()
    now=time.time()+1.0

    c=sqlite3.connect(os.environ["CONTEXT_DB_PATH"])
    c.execute("CREATE TABLE context_samples(id INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL,pair TEXT,source TEXT,kind TEXT,payload TEXT)")

    # Dynamic universe includes XRP, proving mapping is not hard-coded to BTC/ETH/SOL.
    c.execute(
        "INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",
        (now,"XRP/USDT:USDT","bybit","market",json.dumps({"last_price":1.0}))
    )

    # Same logical story syndicated by two RSS sources -> should deduplicate.
    p1={"title":"XRP ETF approval boosts demand","summary":"Institutional demand rises after an XRP ETF approval.","url":"https://source-a.test/xrp","feed":"source-a"}
    p2={"title":"XRP ETF approval boosts investor demand","summary":"An XRP ETF approval is followed by stronger investor demand.","url":"https://source-b.test/xrp","feed":"source-b"}
    c.execute("INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",(now,"*","rss","headline",json.dumps(p1)))
    c.execute("INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",(now+0.2,"*","rss","headline",json.dumps(p2)))
    c.commit(); c.close()

    a._model=lambda:("qwen-test",None)
    a._analyze=lambda item,model:a.normalize(
        {"sentiment":"BULLISH","assets":["XRP"],"confidence":0.9,"importance":0.8,"scope":"ASSET","reason":"test bullish"},
        item["title"]+" "+item["summary"],
        allowed_assets=a._universe_assets(now),
    )

    r=a.refresh_now()
    assert r["analyzed"]==1,r
    assert r["deduped"]==1,r
    assert "XRP" in r["universe_assets"],r

    agg=a.aggregate("XRP/USDT:USDT",now+1)
    assert agg["tone"]=="BULLISH",agg
    fresh_weight=float(agg["effective_weight"])
    aged=a.aggregate("XRP/USDT:USDT",now+90*60)
    assert 0<float(aged["effective_weight"])<fresh_weight,(agg,aged)

    def result(price):
        return {
            "pair":"XRP/USDT:USDT","direction":"LONG","action":"DROP","reason":"selftest",
            "signal":{"direction":"LONG"},
            "market":{"last_price":price},
            "edge":{"total_cost_pct":0.10},
        }

    first=result(100.0)
    x=o.observe_results([first],now=now+2)
    assert x["status"]=="ok" and x["created"]==3,x
    assert first["action"]=="DROP",first
    assert first["news_intelligence"]["state"]=="ALIGNED",first["news_intelligence"]

    later=result(101.0)
    y=o.observe_results([later],now=now+302)
    assert y["closed"]>=1,y
    rep=o.report()
    h=rep["by_horizon"]["300"]
    assert h["ALIGNED"]["n"]>=1,h
    assert h["ALIGNED"]["avg_net_pct"]>0,h

    print("NEWS_INTELLIGENCE_SELFTEST_OK")
    print("dynamic_universe=",r["universe_assets"])
    print("deduped=",r["deduped"],"analyzed=",r["analyzed"])
    print("fresh_weight=",round(fresh_weight,4),"aged_weight=",round(float(aged["effective_weight"]),4))
    print("tone=",agg["tone"],"score=",round(agg["score"],3))
    print("5m_aligned_n=",h["ALIGNED"]["n"])
    print("5m_aligned_avg_net=",round(h["ALIGNED"]["avg_net_pct"],4))
    print("trading_action_preserved=",first["action"])

if __name__=="__main__": run()
