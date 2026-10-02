from __future__ import annotations
import json, os, sys, time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
KYIV=ZoneInfo("Europe/Kyiv")
BANK=HERE/"bank_guard.json"
load_dotenv(HERE/".env"); load_dotenv(ROOT/".env")

def ei(k,d):
    try:return int(os.getenv(k,d))
    except:return int(d)

WARN=max(1,ei("P2P_BANK_WARN_TRANSFERS_PER_DAY","4"))
MAX=max(WARN,ei("P2P_BANK_MAX_TRANSFERS_PER_DAY","6"))
PER=max(1,ei("P2P_BANK_TRANSFERS_PER_CYCLE","2"))
COOLDOWN=max(0,ei("P2P_BANK_MIN_MINUTES_BETWEEN_CYCLES","60"))

def load():
    today=datetime.now(KYIV).date().isoformat()
    try:b=json.loads(BANK.read_text(encoding="utf-8"))
    except:b={}
    if b.get("date")!=today:
        b={"date":today,"confirmed_cycles":0,"confirmed_transfers":0,"alerts_sent":0,"paused":False,"pause_reason":"","last_cycle_ts":0}
    return b

def save(b):BANK.write_text(json.dumps(b,ensure_ascii=False,indent=2),encoding="utf-8")

def status(b):
    used=int(b.get("confirmed_transfers",0)); cycles=int(b.get("confirmed_cycles",0)); last=float(b.get("last_cycle_ts",0) or 0)
    wait=max(0,int(COOLDOWN*60-(time.time()-last))) if last and COOLDOWN else 0
    auto=used>=MAX
    paused=bool(b.get("paused")) or auto
    level="STOP" if paused else ("WARN" if used>=WARN or used+PER>=MAX else "OK")
    reason=b.get("pause_reason") or (f"daily protective threshold reached: {used}/{MAX}" if auto else "")
    print(f"MYSHKA BANK GUARD: {level}")
    print(f"Date: {b.get('date')}")
    print(f"Confirmed cycles: {cycles}")
    print(f"Confirmed bank transfers: {used}/{MAX} (warn at {WARN})")
    print(f"Transfers counted per cycle: {PER}")
    print(f"Cooldown: {wait//60 + (1 if wait%60 else 0)} min remaining" if wait else "Cooldown: ready")
    print(f"Paused: {'YES' if paused else 'NO'}")
    if reason:print("Reason:",reason)

def main():
    action=(sys.argv[1].lower() if len(sys.argv)>1 else "status")
    b=load()
    if action=="cycle":
        b["confirmed_cycles"]=int(b.get("confirmed_cycles",0))+1
        b["confirmed_transfers"]=int(b.get("confirmed_transfers",0))+PER
        b["last_cycle_ts"]=time.time()
        if b["confirmed_transfers"]>=MAX:
            b["paused"]=True
            b["pause_reason"]=f"daily protective threshold reached: {b['confirmed_transfers']}/{MAX}"
        save(b)
    elif action=="pause":
        b["paused"]=True;b["pause_reason"]="manual pause";save(b)
    elif action=="resume":
        b["paused"]=False;b["pause_reason"]="";save(b)
    elif action=="reset":
        b={"date":datetime.now(KYIV).date().isoformat(),"confirmed_cycles":0,"confirmed_transfers":0,"alerts_sent":0,"paused":False,"pause_reason":"","last_cycle_ts":0};save(b)
    elif action!="status":
        raise SystemExit("usage: bank_guard.py [status|cycle|pause|resume|reset]")
    status(load())

if __name__=="__main__":main()
