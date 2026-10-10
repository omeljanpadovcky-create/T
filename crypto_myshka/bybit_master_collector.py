"""Read-only authorized Master Trader feed ingestion. Never execute trades."""
import json, os, urllib.request, urllib.parse, datetime, pathlib
ROOT=pathlib.Path(__file__).resolve().parent
OUT=ROOT/'data'/'bybit_master_research.json'
def main():
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    result={'updated_at':now,'status':'unconfigured','source':'authorized_feed','traders':[],'trades':[],'analysis':{'status':'awaiting_verified_trades'}}
    url=os.getenv('BYBIT_MASTER_FEED_URL','').strip()
    if url:
        parsed=urllib.parse.urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Feed must be a credential-free HTTPS URL')
        allow=os.getenv('BYBIT_MASTER_FEED_HOST','').strip().lower()
        if not allow or parsed.hostname.lower()!=allow: raise ValueError('Feed hostname not explicitly approved')
        req=urllib.request.Request(url,headers={'User-Agent':'CryptoMyshkaResearch/1.0','Accept':'application/json'})
        with urllib.request.urlopen(req,timeout=18) as resp:
            if resp.status!=200: raise ValueError('Feed unavailable')
            payload=resp.read(1000000)
        data=json.loads(payload)
        if not isinstance(data,dict) or not isinstance(data.get('trades'),list): raise ValueError('Expected trades array')
        trades=[];seen=set()
        for t in data['trades'][:3000]:
            if not isinstance(t,dict): continue
            name=str(t.get('trader','')).strip()[:80]
            symbol=str(t.get('symbol','')).strip().upper()[:24]
            side=str(t.get('side','')).strip()
            opened=str(t.get('opened_at',''))[:40]
            source=str(t.get('source_url',''))[:400]
            try: entry=float(t.get('entry_price',0));exitprice=float(t.get('exit_price',0) or 0)
            except (TypeError,ValueError): continue
            if not name or not symbol.isalnum() or side not in ('Buy','Sell','Long','Short') or not opened or entry<=0 or not source.startswith('https://www.bybit.com/'):continue
            key=(name,symbol,side,opened,entry)
            if key in seen:continue
            seen.add(key)
            trades.append({'trader':name,'symbol':symbol,'side':side,'opened_at':opened,'entry_price':entry,'closed_at':str(t.get('closed_at',''))[:40],'exit_price':exitprice or None,'source_url':source})
        result['trades']=trades[:1000]
        result['traders']=sorted({x['trader'] for x in trades})[:10]
        result['status']='ok' if trades else 'empty'
        closed=[t for t in trades if t['exit_price'] and t['closed_at']]
        wins=sum((t['exit_price']-t['entry_price'])*(1 if t['side'] in ('Buy','Long') else -1)>0 for t in closed)
        result['analysis']={'status':'descriptive_only','trades':len(trades),'closed':len(closed),'directional_win_rate_pct':round(wins/len(closed)*100,1) if closed else None,'note':'Price direction only; excludes fees, leverage, funding and slippage. No AI verdict or orders.'}
    OUT.parent.mkdir(parents=True,exist_ok=True)
    OUT.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(f"Master feed: {result['status']}, trades: {len(result['trades'])}")
if __name__=='__main__':main()
