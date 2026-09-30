from __future__ import annotations
import json, os, sqlite3, tempfile, time, uuid
from pathlib import Path

def run():
    root=Path(tempfile.gettempdir())/("myshka_rescue_test_"+uuid.uuid4().hex)
    root.mkdir(parents=True,exist_ok=True)
    risk=root/"risk.sqlite3"
    rescue=root/"rescue.sqlite3"
    os.environ["RISK_INTELLIGENCE_DB_PATH"]=str(risk)
    os.environ["RESCUE_MATRIX_DB_PATH"]=str(rescue)
    os.environ["RESCUE_MATRIX_HIST_MIN_CLUSTER"]="5"
    os.environ["RESCUE_MATRIX_FORWARD_REVIEW_CLUSTER"]="150"

    from . import rescue_matrix as rm

    c=sqlite3.connect(risk)
    c.execute("""CREATE TABLE risk_candidates(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      pair TEXT,side TEXT,opened_at REAL,status TEXT,net_pct REAL,
      tech_score INTEGER,edge_pct REAL,regime TEXT,jev_verdict TEXT)""")
    c.execute("""CREATE TABLE decision_blackbox(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      pair TEXT,observed_at REAL,direction TEXT,stage_json TEXT,raw_json TEXT)""")
    c.commit()

    rm.init()
    start=rm._forward_started()

    rid=0
    # Historical discovery cohort: 6 independent clusters, each duplicated once.
    for cluster in range(6):
        base=start-3600+cluster*300
        for off in (0,15):
            rid+=1
            c.execute("""INSERT INTO risk_candidates(pair,side,opened_at,status,net_pct,tech_score,edge_pct,regime,jev_verdict)
                         VALUES(?,?,?,?,?,?,?,?,?)""",
                      ("BTC/USDT:USDT","LONG",base+off,"CLOSED",0.24,3,0.07,"UP","APPROVE"))
            stage={"evidence_gate":{"applies":True,"passed":True,"state":"PASS"}}
            raw={"binance_crosscheck":{"state":"CONFLICT"}}
            c.execute("INSERT INTO decision_blackbox(pair,observed_at,direction,stage_json,raw_json) VALUES(?,?,?,?,?)",
                      ("BTC/USDT:USDT",base+off+2,"LONG",json.dumps(stage),json.dumps(raw)))

    # Historical negative comparison cohort.
    for cluster in range(5):
        base=start-7200+cluster*300
        c.execute("""INSERT INTO risk_candidates(pair,side,opened_at,status,net_pct,tech_score,edge_pct,regime,jev_verdict)
                     VALUES(?,?,?,?,?,?,?,?,?)""",
                  ("ETH/USDT:USDT","SHORT",base,"CLOSED",-0.30,4,0.18,"DOWN","APPROVE"))
        stage={"evidence_gate":{"applies":True,"passed":False,"state":"HOLD"}}
        raw={"binance_crosscheck":{"state":"AGREE"}}
        c.execute("INSERT INTO decision_blackbox(pair,observed_at,direction,stage_json,raw_json) VALUES(?,?,?,?,?)",
                  ("ETH/USDT:USDT",base+1,"SHORT",json.dumps(stage),json.dumps(raw)))

    # Forward-only cohort after install cutoff.
    for cluster in range(3):
        base=start+60+cluster*300
        c.execute("""INSERT INTO risk_candidates(pair,side,opened_at,status,net_pct,tech_score,edge_pct,regime,jev_verdict)
                     VALUES(?,?,?,?,?,?,?,?,?)""",
                  ("XRP/USDT:USDT","LONG",base,"CLOSED",0.18,3,0.08,"UP","APPROVE"))
        stage={"evidence_gate":{"applies":False,"passed":None,"state":"WARMING"}}
        raw={"binance_crosscheck":{"state":"CONFLICT"}}
        c.execute("INSERT INTO decision_blackbox(pair,observed_at,direction,stage_json,raw_json) VALUES(?,?,?,?,?)",
                  ("XRP/USDT:USDT",base+1,"LONG",json.dumps(stage),json.dumps(raw)))
    c.commit(); c.close()

    rep=rm.report()
    assert rep["status"]=="ok",rep
    assert rep["mode"]=="RESCUE_MATRIX_SHADOW",rep
    hist=rep["historical"]; fwd=rep["forward"]
    assert hist["blackbox_join_coverage_pct"]>95,hist
    assert hist["overall"]["n"]==20,hist["overall"]
    assert hist["overall"]["cluster_n"]<hist["overall"]["n"],hist["overall"]
    positives=hist["matrix"]["top_positive_intersections"]
    assert positives,rep
    found=False
    for x in positives:
        vals=x.get("values") or {}
        if vals.get("tech")=="3/4" and vals.get("xcheck")=="CONFLICT":
            found=True
            assert x["cluster_n"]>=5,x
            assert x["cluster_avg_net_pct"]>0,x
            assert x["disposition"]=="DISCOVERY_ONLY",x
            break
    assert found,positives[:10]

    assert fwd["raw_rows"]==3,fwd
    assert fwd["matrix"]["approved_metrics"]["cluster_n"]==3,fwd
    assert not any(bool(x.get("forward_review_eligible")) for x in fwd["matrix"]["top_positive_intersections"]),fwd

    assert rep["changes_paper_execution"] is False
    assert rep["changes_trading_decisions"] is False
    assert rep["live_execution"] is False

    print("RESCUE_MATRIX_SELFTEST_OK")
    print("historical_raw=",hist["overall"]["n"],"historical_cluster=",hist["overall"]["cluster_n"])
    print("blackbox_join_pct=",round(hist["blackbox_join_coverage_pct"],1))
    print("positive_intersections=",len(positives))
    print("forward_cluster_n=",fwd["matrix"]["approved_metrics"]["cluster_n"])
    print("paper_changed=",rep["changes_paper_execution"])
    print("live_execution=",rep["live_execution"])

if __name__=="__main__":
    run()
