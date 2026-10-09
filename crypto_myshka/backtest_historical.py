#!/usr/bin/env python3
"""Research-only spot backtest. Public Binance candles; no API key or order execution."""
import argparse, csv, datetime as dt, json, math, pathlib, statistics, time, urllib.parse, urllib.request

BASE="https://api.binance.com/api/v3/klines"
def candles(symbol, start, end, interval="1m"):
    cursor=int(dt.datetime.fromisoformat(start).replace(tzinfo=dt.timezone.utc).timestamp()*1000)
    stop=int(dt.datetime.fromisoformat(end).replace(tzinfo=dt.timezone.utc).timestamp()*1000)
    out=[]
    while cursor<stop:
        q=urllib.parse.urlencode(dict(symbol=symbol,interval=interval,startTime=cursor,endTime=stop,limit=1000))
        req=urllib.request.Request(BASE+"?"+q,headers={"User-Agent":"CryptoMyshka-Research/1.0"})
        with urllib.request.urlopen(req,timeout=25) as response: rows=json.load(response)
        if not rows: break
        for r in rows:
            t=int(r[0])
            if t<stop and (not out or t>out[-1][0]):out.append((t,float(r[1]),float(r[2]),float(r[3]),float(r[4])))
        next_cursor=int(rows[-1][0])+1
        if next_cursor<=cursor:break
        cursor=next_cursor
        time.sleep(.15)
    return out

def ema(values,period):
    result=[]; prev=None; alpha=2/(period+1)
    for x in values:
        prev=x if prev is None else alpha*x+(1-alpha)*prev
        result.append(prev)
    return result

def rsi(values,period=14):
    result=[None]*len(values)
    if len(values)<=period:return result
    gains=[max(values[i]-values[i-1],0) for i in range(1,len(values))]
    losses=[max(values[i-1]-values[i],0) for i in range(1,len(values))]
    avg_g=sum(gains[:period])/period; avg_l=sum(losses[:period])/period
    for i in range(period,len(values)):
        if i>period:
            avg_g=(avg_g*(period-1)+gains[i-1])/period
            avg_l=(avg_l*(period-1)+losses[i-1])/period
        result[i]=100 if avg_l==0 else 100-100/(1+avg_g/avg_l)
    return result

def evaluate(rows,fee=.0012,slippage=.0002,fast=9,slow=21,threshold=55):
    """Signal from fully closed candle i; fill next candle open. Long-only spot."""
    if len(rows)<slow+3:return {"error":"insufficient candles","candles":len(rows)}
    closes=[r[4] for r in rows]; a=ema(closes,fast); b=ema(closes,slow); strength=rsi(closes)
    cash=1.; units=0.; entry_value=0.; wins=[]; equity=[1.]; entries=0
    cost=fee+slippage
    for i in range(slow+1,len(rows)):
        prev=i-1; px=rows[i][1]
        buy=a[prev]>b[prev] and a[prev-1]<=b[prev-1] and strength[prev] is not None and strength[prev]>=threshold
        sell=a[prev]<b[prev] and a[prev-1]>=b[prev-1]
        if units and sell:
            proceeds=units*px*(1-cost)
            wins.append(proceeds/entry_value-1)
            cash=proceeds;units=0.;entry_value=0.
        elif not units and buy:
            entry_value=cash
            units=cash*(1-cost)/px
            cash=0.;entries+=1
        equity.append(cash+units*rows[i][4]*(1-cost) if units else cash)
    if units:
        proceeds=units*rows[-1][4]*(1-cost)
        wins.append(proceeds/entry_value-1)
        cash=proceeds
        equity[-1]=cash
    peak=1.;dd=0.
    for value in equity:
        peak=max(peak,value);dd=min(dd,value/peak-1)
    return {"candles":len(rows),"trades":entries,"closed_trades":len(wins),
            "return_pct":round((equity[-1]-1)*100,3),
            "max_drawdown_pct":round(dd*100,3),
            "win_rate_pct":round(100*sum(x>0 for x in wins)/len(wins),2) if wins else None,
            "buy_hold_pct":round((rows[-1][4]/rows[0][1]-1)*100,3),
            "cost_per_side_pct":round(cost*100,4)}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--symbols",nargs="+",default=["BTCUSDT","ETHUSDT","SOLUSDT"])
    p.add_argument("--start",required=True,help="UTC YYYY-MM-DD")
    p.add_argument("--end",required=True,help="UTC YYYY-MM-DD (exclusive)")
    p.add_argument("--fee",type=float,default=.0012,help="per-side fee+spread fraction, conservative placeholder")
    p.add_argument("--slippage",type=float,default=.0002,help="per-side fraction")
    p.add_argument("--out",default="crypto_myshka/data/backtest_results.json")
    args=p.parse_args()
    if args.start>=args.end or args.fee<0 or args.slippage<0:p.error("invalid dates or costs")
    result={"research_only":True,"strategy":"EMA9/21 cross with RSI14>=55; long only; next-open fill",
            "assumptions":{"fee_per_side":args.fee,"slippage_per_side":args.slippage,
            "market":"Binance spot (NOT OTC, futures or binary options)"},
            "period_utc":[args.start,args.end],"results":{}}
    for symbol in args.symbols:
        try:
            rows=candles(symbol,args.start,args.end)
            split=int(len(rows)*.7)
            result["results"][symbol]={"train":evaluate(rows[:split],args.fee,args.slippage),
                                        "out_of_sample":evaluate(rows[split:],args.fee,args.slippage)}
        except Exception as exc:
            result["results"][symbol]={"error":str(exc)}
    target=pathlib.Path(args.out);target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
