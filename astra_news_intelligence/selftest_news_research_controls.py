from __future__ import annotations
import json, os, sqlite3, tempfile, time, uuid
from pathlib import Path

def _mk_context(path,now):
    c=sqlite3.connect(path)
    c.execute("CREATE TABLE context_samples(id INTEGER PRIMARY KEY AUTOINCREMENT,ts REAL,pair TEXT,source TEXT,kind TEXT,payload TEXT)")
    c.execute("INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",
              (now,"BTC/USDT:USDT","bybit","market",json.dumps({"last_price":100.0})))
    c.execute("INSERT INTO context_samples(ts,pair,source,kind,payload) VALUES(?,?,?,?,?)",
              (now,"*","rss","headline",json.dumps({"title":"Bitcoin ETF approved","summary":"fresh","feed":"https://coindesk.com/rss"})))
    c.commit(); c.close()

def _mk_news(path,now):
    c=sqlite3.connect(path)
    c.execute("""CREATE TABLE news_analysis(
      id INTEGER PRIMARY KEY AUTOINCREMENT,source_key TEXT,source_ts REAL,title TEXT,summary TEXT,url TEXT,feed TEXT,
      analyzed_at REAL,status TEXT,sentiment TEXT,sentiment_score REAL,confidence REAL,importance REAL,scope TEXT,
      assets_json TEXT,reason TEXT,model TEXT,error TEXT,event_type TEXT,pre_moves_json TEXT,surprise_json TEXT,
      post_moves_json TEXT,story_id TEXT,lifecycle_stage TEXT,feeds_json TEXT,source_count INTEGER)""")
    c.execute("""INSERT INTO news_analysis(source_key,source_ts,title,summary,url,feed,analyzed_at,status,sentiment,
      sentiment_score,confidence,importance,scope,assets_json,reason,model,error,event_type,story_id,lifecycle_stage,feeds_json,source_count)
      VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
      ("k",now,"Bitcoin ETF approved","fresh","u","https://coindesk.com/rss",now,"OK","BULLISH",1.0,.9,.8,"ASSET",
       json.dumps(["BTC"]),"test","qwen","", "ETF","story1","CONFIRMED",json.dumps(["https://coindesk.com/rss"]),1))
    c.commit(); c.close()

def _mk_analytics(path,rows):
    c=sqlite3.connect(path)
    c.execute("""CREATE TABLE analytics_trades(
      id INTEGER PRIMARY KEY AUTOINCREMENT,pair TEXT,side TEXT,regime TEXT,mode TEXT,tech_score INTEGER,
      opened_at REAL,closed_at REAL,status TEXT,entry_price REAL,expected_edge_pct REAL,total_cost_pct REAL,
      rsi REAL,volume_ratio REAL,context_samples INTEGER,context_age_sec REAL,price_5m_pct REAL,price_15m_pct REAL,
      price_30m_pct REAL,oi_5m_pct REAL,oi_15m_pct REAL,oi_30m_pct REAL,funding_rate_pct REAL,long_short_ratio REAL,
      btc_5m_pct REAL,btc_15m_pct REAL,btc_30m_pct REAL,external_event_count INTEGER,gross_pct REAL,net_pct REAL,
      direction_hit INTEGER,close_note TEXT,raw_entry_json TEXT)""")
    now=time.time()
    for i,net in enumerate(rows):
        c.execute("INSERT INTO analytics_trades(pair,side,mode,tech_score,opened_at,status,gross_pct,net_pct,direction_hit) VALUES(?,?,?,?,?,?,?,?,?)",
                  ("BTC/USDT:USDT","LONG","STRICT",4,now+i,"CLOSED",net+.1,net,1 if net>0 else 0))
    c.commit(); c.close()

def _mk_hardening(path,now):
    c=sqlite3.connect(path)
    c.execute("""CREATE TABLE data_quality_samples(
      id INTEGER PRIMARY KEY AUTOINCREMENT,observed_at REAL,result_count INTEGER,expected_universe INTEGER,
      ok_count INTEGER,total_count INTEGER,state TEXT,issues_json TEXT,checks_json TEXT)""")
    c.execute("INSERT INTO data_quality_samples(observed_at,result_count,expected_universe,ok_count,total_count,state,issues_json,checks_json) VALUES(?,?,?,?,?,?,?,?)",
              (now,15,15,8,8,"OK","[]","[]"))
    c.commit(); c.close()

def run():
    root=Path(tempfile.gettempdir())/("myshka_readiness_test_"+uuid.uuid4().hex)
    root.mkdir(parents=True,exist_ok=True)
    now=time.time()
    os.environ["NEWS_INTELLIGENCE_DB_PATH"]=str(root/"news.sqlite3")
    os.environ["CONTEXT_DB_PATH"]=str(root/"context.sqlite3")
    os.environ["ANALYTICS_DB_PATH"]=str(root/"analytics.sqlite3")
    os.environ["HARDENING_DB_PATH"]=str(root/"hardening.sqlite3")
    os.environ["LIVE_READINESS_MIN_STRICT"]="150"
    os.environ["LIVE_READINESS_MIN_PF"]="1.20"

    _mk_context(os.environ["CONTEXT_DB_PATH"],now)
    _mk_news(os.environ["NEWS_INTELLIGENCE_DB_PATH"],now)
    _mk_analytics(os.environ["ANALYTICS_DB_PATH"],[.2]*20)
    _mk_hardening(os.environ["HARDENING_DB_PATH"],now)

    from . import news_research_controls as rc

    q=rc.news_quality_report()
    assert q["status"]=="ok",q
    assert q["state"] in {"OK","WARN"},q

    stories=rc.story_report()
    assert stories["story_count_72h"]>=1,stories

    blocked=rc.live_readiness_report()
    assert blocked["state"]=="BLOCKED",blocked
    assert any(x["name"]=="clean_strict_sample" and not x["ok"] for x in blocked["checks"]),blocked
    assert blocked["can_enable_live"] is False

    # Replace analytics DB with 150 stable positive STRICT samples.
    os.remove(os.environ["ANALYTICS_DB_PATH"])
    vals=[.20]*50+[.15]*50+[.10]*50
    _mk_analytics(os.environ["ANALYTICS_DB_PATH"],vals)
    eligible=rc.live_readiness_report()
    assert eligible["state"]=="ELIGIBLE_FOR_MANUAL_REVIEW",eligible
    assert eligible["can_enable_live"] is False

    print("NEWS_RESEARCH_CONTROLS_SELFTEST_OK")
    print("quality=",q["state"])
    print("stories=",stories["story_count_72h"])
    print("small_sample_state=",blocked["state"])
    print("mature_sample_state=",eligible["state"])
    print("can_enable_live=",eligible["can_enable_live"])

if __name__=="__main__":
    run()
