from __future__ import annotations
import csv, json, os, subprocess, threading, time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from dotenv import load_dotenv

HERE=Path(__file__).resolve().parent; ROOT=HERE.parent; KYIV=ZoneInfo('Europe/Kyiv')
load_dotenv(HERE/'.env'); load_dotenv(ROOT/'.env')
def ef(k,d):
    try:return float(os.getenv(k,d))
    except:return float(d)
def ei(k,d):
    try:return int(os.getenv(k,d))
    except:return int(d)
def eb(k,d='0'):return os.getenv(k,d).lower() in ('1','true','yes','on')
FIAT=os.getenv('P2P_FIAT','UAH').upper(); ASSET=os.getenv('P2P_ASSET','USDT').upper(); CAPITAL=ef('P2P_CAPITAL_FIAT','4500')
INTERVAL=max(10,ei('P2P_SCAN_SECONDS','20')); MIN_NET=ef('P2P_MIN_NET_PCT','0.35'); MAX_RISK=ei('P2P_MAX_RISK','60')
MIN_RATE=ef('P2P_MIN_COMPLETION','90'); MIN_ORDERS=ei('P2P_MIN_ORDERS','10'); XFER=ef('P2P_TRANSFER_FEE_USDT','1')
BUFFER=ef('P2P_SAFETY_BUFFER_PCT','0.15'); TG_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TG_BOT_TOKEN','')
TG_CHAT=os.getenv('TELEGRAM_CHAT_ID') or os.getenv('TG_CHAT_ID',''); BY_KEY=os.getenv('BYBIT_API_KEY',''); BY_SECRET=os.getenv('BYBIT_API_SECRET','')
LATEST=HERE/'latest.json'; HIST=HERE/'history.csv'; REPORTS=HERE/'reports'; STATE=HERE/'state.json'; BANK=HERE/'bank_guard.json'; REPORTS.mkdir(exist_ok=True)
BANK_WARN=max(1,ei('P2P_BANK_WARN_TRANSFERS_PER_DAY','4')); BANK_MAX=max(BANK_WARN,ei('P2P_BANK_MAX_TRANSFERS_PER_DAY','6'))
BANK_PER_CYCLE=max(1,ei('P2P_BANK_TRANSFERS_PER_CYCLE','2')); BANK_COOLDOWN=max(0,ei('P2P_BANK_MIN_MINUTES_BETWEEN_CYCLES','60')); BANK_ALERT_MAX=max(1,ei('P2P_BANK_MAX_ALERTS_PER_DAY','8')); TG_CONFIRM_WARN=max(1,ei('P2P_TELEGRAM_CONFIRM_WARN','5')); GIT_SYNC_SECONDS=max(30,ei('P2P_GIT_SYNC_SECONDS','60'))
DASHBOARD_URL=os.getenv('P2P_DASHBOARD_URL','https://omeljanpadovcky-create.github.io/T/').strip()
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 Myshka-P2P-Radar/2.0'

@dataclass
class Offer:
    exchange:str; action:str; price:float; min_fiat:float; max_fiat:float; merchant:str; completion:float|None; orders:int|None; payments:list[str]; source:str
    def fits(self): return self.price>0 and self.min_fiat<=CAPITAL<=(self.max_fiat or 1e99)

def num(x,d=0.0):
    try:return float(str(x).replace(',','.'))
    except:return d
def rate(x):
    if x in (None,'','--'):return None
    v=num(x,-1)
    if v<0:return None
    return min(100,max(0,v*100 if v<=1 else v))
def keep(xs,action):
    xs=[x for x in xs if x.fits() and (x.completion is None or x.completion>=MIN_RATE) and (x.orders is None or x.orders>=MIN_ORDERS)]
    return sorted(xs,key=lambda x:x.price,reverse=action=='SELL')[:15]

def binance():
    if not eb('P2P_BINANCE_ENABLED','1'): return {'exchange':'Binance','ok':False,'note':'disabled','buy':[],'sell':[]}
    url='https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'
    def get(action):
        body={'fiat':FIAT,'page':1,'rows':20,'tradeType':action,'asset':ASSET,'countries':[],'proMerchantAds':False,'shieldMerchantAds':False,'publisherType':None,'payTypes':[]}
        r=S.post(url,json=body,headers={'Origin':'https://p2p.binance.com','Referer':'https://p2p.binance.com/'},timeout=10); r.raise_for_status(); out=[]
        for row in r.json().get('data') or []:
            a=row.get('adv') or {}; m=row.get('advertiser') or {}; pays=[p.get('tradeMethodName') or p.get('identifier') for p in a.get('tradeMethods') or []]
            orders=int(num(m.get('monthOrderCount') or m.get('monthFinishCount'),0)) or None
            out.append(Offer('Binance',action,num(a.get('price')),num(a.get('minSingleTransAmount')),num(a.get('dynamicMaxSingleTransAmount') or a.get('maxSingleTransAmount')),str(m.get('nickName') or 'unknown'),rate(m.get('monthFinishRate') or m.get('positiveRate')),orders,[str(p) for p in pays if p],'web-feed'))
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL'); return {'exchange':'Binance','ok':bool(b or s),'note':f'{len(b)} buy / {len(s)} sell','buy':b,'sell':s}
    except Exception as e:return {'exchange':'Binance','ok':False,'note':f'{type(e).__name__}: {e}','buy':[],'sell':[]}

def bybit():
    if not eb('P2P_BYBIT_ENABLED','1'): return {'exchange':'Bybit','ok':False,'note':'disabled','buy':[],'sell':[]}
    if not BY_KEY or not BY_SECRET:return {'exchange':'Bybit','ok':False,'note':'needs API keys + General Advertiser access','buy':[],'sell':[]}
    try:
        from pybit.unified_trading import HTTP
        api=HTTP(testnet=False,api_key=BY_KEY,api_secret=BY_SECRET)
        def get(action):
            side='1' if action=='BUY' else '0'; raw=api.get_online_ads(tokenId=ASSET,currencyId=FIAT,side=side,page='1',size='20'); out=[]
            for a in (raw.get('result') or {}).get('items') or []:
                pref=a.get('tradingPreferenceSet') or {}; orders=int(num(a.get('recentOrderNum') or pref.get('orderFinishNumberDay30'),0)) or None
                out.append(Offer('Bybit',action,num(a.get('price')),num(a.get('minAmount')),num(a.get('maxAmount')),str(a.get('nickName') or 'unknown'),rate(a.get('recentExecuteRate') or pref.get('completeRateDay30')),orders,[str(x) for x in a.get('payments') or []],'official-api'))
            return keep(out,action)
        b,s=get('BUY'),get('SELL'); return {'exchange':'Bybit','ok':bool(b or s),'note':f'{len(b)} buy / {len(s)} sell','buy':b,'sell':s}
    except Exception as e:return {'exchange':'Bybit','ok':False,'note':f'{type(e).__name__}: {e}','buy':[],'sell':[]}

def offer_risk(o):
    r=16 if o.source=='web-feed' else 0; why=[]
    if o.source=='web-feed':why.append(o.exchange+': web feed may change')
    if o.completion is None:r+=8;why.append(o.exchange+': completion unknown')
    elif o.completion<95:r+=10;why.append(f'{o.exchange}: completion {o.completion:.1f}%')
    if o.orders is None:r+=5
    elif o.orders<30:r+=9;why.append(f'{o.exchange}: only {o.orders} recent orders')
    if not o.payments:r+=4
    return r,why

def routes(providers):
    buys=[o for p in providers if p['ok'] for o in p['buy']]; sells=[o for p in providers if p['ok'] for o in p['sell']]; out=[]
    for b in buys:
      for s in sells:
        same=b.exchange==s.exchange; transfer_fee=0.0 if same else XFER
        qty=CAPITAL/b.price; gross=(s.price/b.price-1)*100; safety=CAPITAL*BUFFER/100
        net=(max(0,qty-transfer_fee)*s.price)-CAPITAL-safety; pref=(qty*s.price)-CAPITAL-safety; rb,wb=offer_risk(b); rs,ws=offer_risk(s); risk=max(rb,rs); why=wb+ws
        if same: why=['same-exchange route: no modeled crypto transfer fee']+why
        drag=(transfer_fee*b.price/CAPITAL*100) if CAPITAL else 0
        if drag>.7:risk+=10;why.append(f'transfer drag {drag:.2f}%')
        if gross>3:risk+=20;why.append('unusually large spread — verify manually')
        elif gross>1.5:risk+=8;why.append('large spread — re-check freshness')
        risk=min(100,risk); netpct=net/CAPITAL*100; prefpct=pref/CAPITAL*100
        verdict='ALERT' if netpct>=MIN_NET and risk<=MAX_RISK else ('PREFUNDED_ONLY' if prefpct>=MIN_NET else 'DROP')
        out.append({'buy_exchange':b.exchange,'sell_exchange':s.exchange,'route_type':'INTRA' if same else 'CROSS','buy_price':round(b.price,4),'sell_price':round(s.price,4),'gross_spread_pct':round(gross,3),'net_profit_fiat':round(net,2),'net_pct':round(netpct,3),'prefunded_net_pct':round(prefpct,3),'risk_score':risk,'verdict':verdict,'buy_merchant':b.merchant,'sell_merchant':s.merchant,'buy_completion_pct':b.completion,'sell_completion_pct':s.completion,'buy_payments':b.payments,'sell_payments':s.payments,'reasons':why[:6]})
    return sorted(out,key=lambda x:(x['verdict']=='ALERT',x['net_pct'],-x['risk_score']),reverse=True)

def public_provider(p):
    return {'exchange':p['exchange'],'ok':p['ok'],'note':p['note'],'buy_offers':len(p['buy']),'sell_offers':len(p['sell']),'best_buy':asdict(p['buy'][0]) if p['buy'] else None,'best_sell':asdict(p['sell'][0]) if p['sell'] else None}
def state():
    try:return json.loads(STATE.read_text(encoding='utf-8'))
    except:return {}
def save_state(x):STATE.write_text(json.dumps(x,indent=2),encoding='utf-8')
def bank_state():
    today=datetime.now(KYIV).date().isoformat()
    try:b=json.loads(BANK.read_text(encoding='utf-8'))
    except:b={}
    if b.get('date')!=today:
        b={'date':today,'confirmed_cycles':0,'confirmed_transfers':0,'alerts_sent':0,'route_checks':0,'paused':False,'pause_reason':'','last_cycle_ts':0}
    return b
def save_bank(b):BANK.write_text(json.dumps(b,ensure_ascii=False,indent=2),encoding='utf-8')
def bank_guard(b):
    now=time.time(); used=int(b.get('confirmed_transfers',0)); alerts=int(b.get('alerts_sent',0)); paused=bool(b.get('paused'))
    reason=str(b.get('pause_reason') or '')
    if used>=BANK_MAX:paused=True;reason=f'daily bank-transfer guard reached: {used}/{BANK_MAX}'
    elif alerts>=BANK_ALERT_MAX:paused=True;reason=f'daily Telegram action-alert guard reached: {alerts}/{BANK_ALERT_MAX}'
    wait=0
    last=float(b.get('last_cycle_ts',0) or 0)
    if last and BANK_COOLDOWN:
        wait=max(0,int(BANK_COOLDOWN*60-(now-last)))
    level='STOP' if paused else ('WARN' if used>=BANK_WARN or used+BANK_PER_CYCLE>=BANK_MAX else 'OK')
    return {'level':level,'paused':paused,'reason':reason,'confirmed_transfers':used,'confirmed_cycles':int(b.get('confirmed_cycles',0)),'alerts_sent':alerts,'warn_at':BANK_WARN,'max_transfers':BANK_MAX,'transfers_per_cycle':BANK_PER_CYCLE,'cooldown_minutes':BANK_COOLDOWN,'cooldown_remaining_seconds':wait}

def exchange_url(exchange,action):
    e=str(exchange or '').lower(); side='buy' if str(action).upper()=='BUY' else 'sell'
    if e=='binance':
        return f"https://p2p.binance.com/en/trade/{side}/{ASSET}?fiat={FIAT}"
    if e=='bybit':
        return "https://www.bybit.com/fiat/trade/otc/"
    return ""

def telegram_keyboard(r):
    row=[]
    bu=exchange_url(r.get('buy_exchange'),'BUY'); su=exchange_url(r.get('sell_exchange'),'SELL')
    if bu:row.append({'text':f"🟢 BUY {r.get('buy_exchange','')} ",'url':bu})
    if su:row.append({'text':f"🔴 SELL {r.get('sell_exchange','')} ",'url':su})
    kb=[]
    if row:kb.append(row)
    if DASHBOARD_URL:kb.append([{'text':'📊 Відкрити радар','url':DASHBOARD_URL}])
    kb.append([{'text':'🔗 Я перевірив маршрут','callback_data':'p2p_route_checked'},{'text':'✅ Цикл завершено','callback_data':'p2p_cycle_done'}])
    kb.append([{'text':'⏸ Пауза alerts','callback_data':'p2p_pause'},{'text':'📋 Статус','callback_data':'p2p_status'}])
    return {'inline_keyboard':kb}

def telegram(t,reply_markup=None):
    if not TG_TOKEN or not TG_CHAT:return False,'not configured'
    try:
        payload={'chat_id':TG_CHAT,'text':t,'disable_web_page_preview':True}
        if reply_markup:payload['reply_markup']=reply_markup
        r=S.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',json=payload,timeout=10); return r.ok,('sent' if r.ok else f'HTTP {r.status_code}')
    except Exception as e:return False,str(e)

def callback_answer(qid,text='',show=False):
    try:S.post(f'https://api.telegram.org/bot{TG_TOKEN}/answerCallbackQuery',json={'callback_query_id':qid,'text':text[:190],'show_alert':bool(show)},timeout=10)
    except Exception:pass

def bank_apply(action):
    b=bank_state()
    if action=='cycle-done':
        b['confirmed_cycles']=int(b.get('confirmed_cycles',0))+1
        b['confirmed_transfers']=int(b.get('confirmed_transfers',0))+BANK_PER_CYCLE
        b['last_cycle_ts']=time.time()
        if b['confirmed_transfers']>=BANK_MAX:
            b['paused']=True;b['pause_reason']=f'daily protective threshold reached: {b["confirmed_transfers"]}/{BANK_MAX}'
    elif action=='route-checked':
        b['route_checks']=int(b.get('route_checks',0))+1
    elif action=='pause':
        b['paused']=True;b['pause_reason']='manual pause'
    elif action=='resume':
        b['paused']=False;b['pause_reason']=''
    elif action=='reset-bank':
        b={'date':datetime.now(KYIV).date().isoformat(),'confirmed_cycles':0,'confirmed_transfers':0,'alerts_sent':0,'route_checks':0,'paused':False,'pause_reason':'','last_cycle_ts':0}
    save_bank(b);return b,bank_guard(b)

def telegram_status_text():
    b=bank_state(); bg=bank_guard(b)
    return (f"🐭 MYSHKA P2P STATUS\nBank Guard: {bg['level']}\n"
            f"Підтверджені цикли: {bg['confirmed_cycles']}\n"
            f"Підтверджені bank transfers: {bg['confirmed_transfers']}/{bg['max_transfers']}\n"
            f"Перевірок маршрутів: {int(b.get('route_checks',0))} (warning at {TG_CONFIRM_WARN})\n"
            f"Telegram alerts: {bg['alerts_sent']}/{BANK_ALERT_MAX}\n"
            f"Cooldown: {bg['cooldown_remaining_seconds']//60} min\n"
            f"Alerts paused: {'YES' if bg['paused'] else 'NO'}")

def telegram_control_loop():
    if not TG_TOKEN or not TG_CHAT:return
    offset=None
    try:
        r=S.get(f'https://api.telegram.org/bot{TG_TOKEN}/getUpdates',params={'timeout':0,'offset':-1},timeout=5)
        items=(r.json().get('result') or []) if r.ok else []
        if items:offset=max(int(x.get('update_id',0)) for x in items)+1
    except Exception:pass
    while True:
        try:
            params={'timeout':20,'allowed_updates':json.dumps(['callback_query','message'])}
            if offset is not None:params['offset']=offset
            r=S.get(f'https://api.telegram.org/bot{TG_TOKEN}/getUpdates',params=params,timeout=30)
            if not r.ok:time.sleep(3);continue
            for u in r.json().get('result') or []:
                offset=int(u.get('update_id',0))+1
                q=u.get('callback_query') or {}
                if q:
                    chat=str(((q.get('message') or {}).get('chat') or {}).get('id',''))
                    if chat!=str(TG_CHAT):continue
                    data=str(q.get('data') or '');qid=str(q.get('id') or '')
                    if data=='p2p_route_checked':
                        b,bg=bank_apply('route-checked');n=int(b.get('route_checks',0));warn=n>=TG_CONFIRM_WARN
                        callback_answer(qid,(f"⚠️ Уже {n} перевірок сьогодні. Звір ліміти банку/картки перед наступною дією." if warn else f"Перевірка #{n} зарахована."),warn)
                        if n==TG_CONFIRM_WARN:telegram(f"⚠️ MYSHKA P2P: сьогодні вже {n} разів відкривався/перевірявся маршрут. Це внутрішнє попередження, не ліміт банку. Перед наступною операцією перевір актуальні ліміти та реквізити.")
                    elif data=='p2p_cycle_done':
                        b,bg=bank_apply('cycle-done');callback_answer(qid,f"Цикл #{bg['confirmed_cycles']} зараховано · Bank Guard {bg['level']}",bg['level']!='OK')
                    elif data=='p2p_pause':
                        bank_apply('pause');callback_answer(qid,'P2P alerts поставлено на паузу.',True)
                    elif data=='p2p_status':
                        callback_answer(qid,'Статус надіслано');telegram(telegram_status_text())
                    continue
                m=u.get('message') or {};chat=str((m.get('chat') or {}).get('id',''))
                if chat!=str(TG_CHAT):continue
                cmd=str(m.get('text') or '').strip().lower().split()[0] if m.get('text') else ''
                if cmd in {'/p2p','/p2p_status','/status'}:telegram(telegram_status_text())
                elif cmd in {'/p2p_pause','/pause'}:bank_apply('pause');telegram('⏸ MYSHKA P2P alerts paused.')
                elif cmd in {'/p2p_resume','/resume'}:bank_apply('resume');telegram('▶️ MYSHKA P2P alerts resumed.')
                elif cmd in {'/p2p_done','/done'}:
                    _,bg=bank_apply('cycle-done');telegram(f"✅ Цикл #{bg['confirmed_cycles']} зараховано · Bank Guard {bg['level']}.")
                elif cmd in {'/p2p_help','/help'}:telegram("MYSHKA P2P commands:\n/p2p_status\n/p2p_pause\n/p2p_resume\n/p2p_done")
        except Exception as e:
            print('TELEGRAM CONTROL:',e,flush=True);time.sleep(4)

def tg_text(r,ts,bg):
    return f"🐭 MYSHKA P2P RADAR\n{r['verdict']} {ASSET}/{FIAT}\nBUY {r['buy_exchange']}: {r['buy_price']:.4f}\nSELL {r['sell_exchange']}: {r['sell_price']:.4f}\nGross {r['gross_spread_pct']:+.2f}%\nNet {r['net_pct']:+.2f}% ≈ {r['net_profit_fiat']:+.2f} {FIAT}\nPrefunded {r['prefunded_net_pct']:+.2f}%\nRisk {r['risk_score']}/100\nBank Guard {bg['level']} · {bg['confirmed_transfers']}/{bg['max_transfers']} confirmed transfers today\nCapital model {CAPITAL:.0f} {FIAT}\nWhy: {'; '.join(r['reasons'][:3]) or 'filters passed'}\n{ts}\nВідкрий BUY/SELL кнопки, звір оголошення, потім натисни «Я перевірив маршрут». На 5-й перевірці MYSHKA покаже warning.\nNo auto-trade. Verify the live P2P ad before payment."
def report(snap):
    d=datetime.now(KYIV); p=REPORTS/f'{d:%Y-%m-%d}.md'; t=snap.get('top_route')
    with p.open('a',encoding='utf-8') as f:
      f.write(f"\n## {d:%H:%M:%S} Kyiv — {ASSET}/{FIAT}\n\nCapital **{CAPITAL:.0f} {FIAT}**, transfer model **{XFER:g} {ASSET}**, buffer **{BUFFER:.2f}%**.\n\n")
      if t:f.write(f"Top: **{t['buy_exchange']} → {t['sell_exchange']}**, BUY {t['buy_price']:.4f}, SELL {t['sell_price']:.4f}, gross {t['gross_spread_pct']:+.2f}%, net {t['net_pct']:+.2f}% ({t['net_profit_fiat']:+.2f} {FIAT}), risk {t['risk_score']}/100, **{t['verdict']}**.\n\n")
      f.write('Providers:\n'+''.join(f"- **{x['exchange']}**: {'OK' if x['ok'] else 'OFF'} — {x['note']}\n" for x in snap['providers']))
    return p
def history(snap):
    t=snap.get('top_route') or {}; new=not HIST.exists()
    with HIST.open('a',encoding='utf-8',newline='') as f:
      w=csv.writer(f)
      if new:w.writerow(['scanned_at','buy','sell','buy_price','sell_price','gross_pct','net_pct','profit_fiat','risk','verdict'])
      w.writerow([snap['scanned_at'],t.get('buy_exchange',''),t.get('sell_exchange',''),t.get('buy_price',''),t.get('sell_price',''),t.get('gross_spread_pct',''),t.get('net_pct',''),t.get('net_profit_fiat',''),t.get('risk_score',''),t.get('verdict','NO_ROUTE')])
def git_push():
    if not eb('P2P_GIT_PUSH','0'):return
    try:
      subprocess.run(['git','add','p2p_radar/latest.json','p2p_radar/history.csv','p2p_radar/reports'],cwd=ROOT,check=True,timeout=15)
      if subprocess.run(['git','diff','--cached','--quiet'],cwd=ROOT).returncode==0:return
      subprocess.run(['git','commit','-m',f"p2p radar: {datetime.now(KYIV):%Y-%m-%d %H:%M Kyiv}"],cwd=ROOT,check=True,timeout=30); subprocess.run(['git','push'],cwd=ROOT,check=True,timeout=60)
    except Exception as e:print('GIT:',e,flush=True)

def scan():
    ts=datetime.now(KYIV).isoformat(timespec='seconds'); ps=[binance(),bybit()]; rs=routes(ps); top=rs[0] if rs else None
    b=bank_state(); bg=bank_guard(b)
    if bg['paused'] and top and top['verdict']=='ALERT':
        top=dict(top); top['verdict']='PAUSE_BANK_GUARD'; top['reasons']=([bg['reason']] if bg['reason'] else ['Bank Guard paused actionable alerts'])+list(top.get('reasons') or [])
    elif bg['cooldown_remaining_seconds']>0 and top and top['verdict']=='ALERT':
        top=dict(top); top['verdict']='COOLDOWN'; top['reasons']=[f"Bank Guard cooldown {bg['cooldown_remaining_seconds']//60+1} min remaining"]+list(top.get('reasons') or [])
    snap={'version':'MYSHKA_P2P_RADAR_V1','scanned_at':ts,'fiat':FIAT,'asset':ASSET,'capital_fiat':CAPITAL,'mode':'SCAN_ONLY_NO_AUTOTRADE','bank_guard':bg,'providers':[public_provider(x) for x in ps],'routes':rs[:25],'top_route':top,'alerts':sum(x['verdict']=='ALERT' for x in rs)}
    LATEST.write_text(json.dumps(snap,ensure_ascii=False,indent=2),encoding='utf-8'); history(snap); st=state(); now=time.time(); did=False
    if top and top['verdict']=='ALERT' and (st.get('last_route')!=f"{top['buy_exchange']}->{top['sell_exchange']}" or now-float(st.get('last_alert',0))>=600):
      ok,msg=telegram(tg_text(top,ts,bg),telegram_keyboard(top)); report(snap); print('TELEGRAM:',msg,flush=True); did=True
      if ok:
        st['last_route']=f"{top['buy_exchange']}->{top['sell_exchange']}"; st['last_alert']=now
        b['alerts_sent']=int(b.get('alerts_sent',0))+1; save_bank(b)
    if now-float(st.get('last_report',0))>=900:report(snap);st['last_report']=now;did=True
    if eb('P2P_GIT_PUSH','0') and now-float(st.get('last_git_sync',0))>=GIT_SYNC_SECONDS:
        git_push();st['last_git_sync']=now
    save_state(st)
    if did and not eb('P2P_GIT_PUSH','0'):git_push()
    print(f"[{datetime.now(KYIV):%H:%M:%S}] "+', '.join(f"{p['exchange']}:{'OK' if p['ok'] else 'OFF'}" for p in ps)+(f" | {top['buy_exchange']}->{top['sell_exchange']} net={top['net_pct']:+.2f}% risk={top['risk_score']} {top['verdict']}" if top else ' | no route'),flush=True)

def bank_command(action):
    b,bg=bank_apply(action)
    out=dict(bg);out['route_checks']=int(b.get('route_checks',0));out['telegram_confirm_warn']=TG_CONFIRM_WARN
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 0

def main():
    args=[x.lower() for x in os.sys.argv[1:]]
    if args and args[0] in {'cycle-done','pause','resume','reset-bank','route-checked'}:
        return bank_command(args[0])
    if '--once' in args:
        scan();return 0
    if TG_TOKEN and TG_CHAT:
        threading.Thread(target=telegram_control_loop,name='myshka-p2p-telegram',daemon=True).start()
    print(f'MYSHKA P2P RADAR V2 — {ASSET}/{FIAT}, {CAPITAL:.0f} {FIAT}, scan {INTERVAL}s, Telegram control ON={bool(TG_TOKEN and TG_CHAT)}, NO AUTO-TRADE',flush=True)
    while True:
      try:scan()
      except KeyboardInterrupt:return
      except Exception as e:print('SCAN ERROR:',e,flush=True)
      time.sleep(INTERVAL)
if __name__=='__main__':main()
