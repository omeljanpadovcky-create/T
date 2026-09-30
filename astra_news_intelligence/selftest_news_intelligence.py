from __future__ import annotations
import json, os, sqlite3, tempfile, time, uuid, sys, types
from pathlib import Path

# The synthetic self-test does not perform HTTP. On Windows the host Python may
# not have requests installed even though the Docker image does. Provide a tiny
# import stub so the test validates our DB/aggregation/outcome logic only.
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

    from . import news_analyzer as a
    from . import news_outcomes as o

    o.init()
    now=time.time()+1.0
    c=sqlite3.connect(os.environ["CONTEXT_DB_PATH"])
    c.execute("CREATE TABLE context_samples(id INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL,pair TEXT,source TEXT,kind TEXT,payload TEXT)")
    payload={"title":"Bitcoin ETF inflows accelerate","summary":"Strong spot ETF inflows support Bitcoin demand.","url":"https://example.test/btc","feed":"test"}
    c.execute("INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",(now,"*","rss","headline",json.dumps(payload)))
    c.commit(); c.close()

    a._model=lambda:("qwen-test",None)
    a._analyze=lambda item,model:a.normalize({"sentiment":"BULLISH","assets":["BTC"],"confidence":0.9,"importance":0.8,"scope":"ASSET","reason":"test bullish"},item["title"]+" "+item["summary"])

    r=a.refresh_now()
    assert r["analyzed"]==1,r
    agg=a.aggregate("BTC/USDT:USDT",now)
    assert agg["tone"]=="BULLISH",agg

    def result(price):
        return {
            "pair":"BTC/USDT:USDT","direction":"LONG","action":"DROP","reason":"selftest",
            "signal":{"direction":"LONG"},
            "market":{"last_price":price},
            "edge":{"total_cost_pct":0.10},
        }

    first=result(100.0)
    x=o.observe_results([first],now=now)
    assert x["status"]=="ok" and x["created"]==3,x
    assert first["action"]=="DROP",first
    assert first["news_intelligence"]["state"]=="ALIGNED",first["news_intelligence"]

    later=result(101.0)
    y=o.observe_results([later],now=now+300)
    assert y["closed"]>=1,y
    rep=o.report()
    h=rep["by_horizon"]["300"]
    assert h["ALIGNED"]["n"]>=1,h
    assert h["ALIGNED"]["avg_net_pct"]>0,h

    print("NEWS_INTELLIGENCE_SELFTEST_OK")
    print("analyzed=",r["analyzed"])
    print("tone=",agg["tone"],"score=",round(agg["score"],3))
    print("5m_aligned_n=",h["ALIGNED"]["n"])
    print("5m_aligned_avg_net=",round(h["ALIGNED"]["avg_net_pct"],4))
    print("trading_action_preserved=",first["action"])

if __name__=="__main__": run()
