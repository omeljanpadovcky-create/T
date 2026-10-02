from __future__ import annotations
import base64, csv, hashlib, hmac, json, os, subprocess, threading, time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode
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
EXCHANGES_FILE=HERE/os.getenv('P2P_EXCHANGES_FILE','exchanges.json')
INTERVAL=max(10,ei('P2P_SCAN_SECONDS','15')); MARKET_PAGES=max(1,min(5,ei('P2P_MARKET_PAGES','3'))); KEEP_PER_SIDE=max(15,min(60,ei('P2P_KEEP_OFFERS_PER_SIDE','40'))); MIN_NET=ef('P2P_MIN_NET_PCT','0.35'); MAX_RISK=ei('P2P_MAX_RISK','60'); REVIEW_SPREAD=ef('P2P_REVIEW_SPREAD_PCT','3.0')
MIN_RATE=ef('P2P_MIN_COMPLETION','90'); MIN_ORDERS=ei('P2P_MIN_ORDERS','10'); XFER=ef('P2P_TRANSFER_FEE_USDT','1')
BUFFER=ef('P2P_SAFETY_BUFFER_PCT','0.15'); TG_TOKEN=os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TG_BOT_TOKEN','')
TG_CHAT=os.getenv('TELEGRAM_CHAT_ID') or os.getenv('TG_CHAT_ID','')
BY_KEY=os.getenv('BYBIT_API_KEY',''); BY_SECRET=os.getenv('BYBIT_API_SECRET','')
BITGET_KEY=os.getenv('BITGET_API_KEY',''); BITGET_SECRET=os.getenv('BITGET_API_SECRET',''); BITGET_PASS=os.getenv('BITGET_API_PASSPHRASE','')
GATE_KEY=os.getenv('GATE_API_KEY',''); GATE_SECRET=os.getenv('GATE_API_SECRET','')
OKX_KEY=os.getenv('OKX_API_KEY',''); OKX_SECRET=os.getenv('OKX_API_SECRET',''); OKX_PASS=os.getenv('OKX_API_PASSPHRASE','')
MEXC_KEY=os.getenv('MEXC_API_KEY',''); MEXC_SECRET=os.getenv('MEXC_API_SECRET','')
LATEST=HERE/'latest.json'; HIST=HERE/'history.csv'; REPORTS=HERE/'reports'; STATE=HERE/'state.json'; BANK=HERE/'bank_guard.json'; REPORTS.mkdir(exist_ok=True)
BANK_WARN=max(1,ei('P2P_BANK_WARN_TRANSFERS_PER_DAY','4')); BANK_MAX=max(BANK_WARN,ei('P2P_BANK_MAX_TRANSFERS_PER_DAY','6'))
BANK_PER_CYCLE=max(1,ei('P2P_BANK_TRANSFERS_PER_CYCLE','2')); BANK_COOLDOWN=max(0,ei('P2P_BANK_MIN_MINUTES_BETWEEN_CYCLES','60')); BANK_ALERT_MAX=max(1,ei('P2P_BANK_MAX_ALERTS_PER_DAY','8')); TG_CONFIRM_WARN=max(1,ei('P2P_TELEGRAM_CONFIRM_WARN','5')); GIT_SYNC_SECONDS=max(30,ei('P2P_GIT_SYNC_SECONDS','60'))
DASHBOARD_URL=os.getenv('P2P_DASHBOARD_URL','https://omeljanpadovcky-create.github.io/T/').strip()
S=requests.Session(); S.headers['User-Agent']='Mozilla/5.0 Myshka-P2P-Radar/2.0'

@dataclass
class Offer:
    exchange:str; action:str; price:float; min_fiat:float; max_fiat:float; merchant:str; completion:float|None; orders:int|None; payments:list[str]; source:str
    def fits(self): return self.price>0

def num(x,d=0.0):
    try:return float(str(x).replace(',','.'))
    except:return d
def rate(x):
    if x in (None,'','--'):return None
    v=num(x,-1)
    if v<0:return None
    return min(100,max(0,v*100 if v<=1 else v))
def keep(xs,action):
    xs=[x for x in xs if x.fits()]
    return sorted(xs,key=lambda x:x.price,reverse=action=='SELL')[:KEEP_PER_SIDE]

def route_eligible(o):
    return (o.completion is None or o.completion>=MIN_RATE) and (o.orders is None or o.orders>=MIN_ORDERS)

def binance():
    if not eb('P2P_BINANCE_ENABLED','1'):
        return {'exchange':'Binance','ok':False,'note':'вимкнено','buy':[],'sell':[]}

    # Primary source: the same friendly C2C web feed used by Binance P2P pages.
    # This generally matches what the user sees in the browser much better than
    # the older agent/ad-list endpoint.
    friendly='https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search'
    headers={
        'User-Agent':S.headers['User-Agent'],
        'Accept':'application/json',
        'Content-Type':'application/json',
        'Origin':'https://p2p.binance.com',
        'Referer':'https://p2p.binance.com/'
    }

    def parse_friendly(action):
        out=[]
        for page in range(1,MARKET_PAGES+1):
            payload={
                'asset':ASSET,
                'fiat':FIAT,
                'page':page,
                'rows':20,
                'tradeType':action,
                'payTypes':[],
                'countries':[],
                'publisherType':None,
                'merchantCheck':False,
                'transAmount':''
            }
            r=S.post(friendly,json=payload,headers=headers,timeout=12)
            r.raise_for_status()
            raw=r.json()
            items=raw.get('data') or []
            if not items: break
            for item in items:
                a=item.get('adv') or {}
                m=item.get('advertiser') or {}
                pays=[]
                for p in a.get('tradeMethods') or []:
                    if isinstance(p,dict):
                        name=p.get('tradeMethodName') or p.get('identifier') or p.get('tradeMethodShortName')
                        if name:pays.append(str(name))
                    elif p:
                        pays.append(str(p))
                out.append(Offer(
                    'Binance',action,
                    num(a.get('price')),
                    num(a.get('minSingleTransAmount')),
                    num(a.get('maxSingleTransAmount')),
                    str(m.get('nickName') or 'unknown'),
                    rate(m.get('monthFinishRate') or m.get('positiveRate')),
                    int(num(m.get('monthOrderCount'),0)) or None,
                    pays,
                    'web-feed'
                ))
            if len(items)<20: break
        return keep(out,action)

    try:
        b,s=parse_friendly('BUY'),parse_friendly('SELL')
        if b or s:
            return {'exchange':'Binance','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · Binance P2P web feed','buy':b,'sell':s}
    except Exception:
        pass

    # Fallback if Binance blocks the friendly feed from the cloud runner.
    fallback='https://www.binance.com/bapi/c2c/v1/public/c2c/agent/ad-list'
    def parse_fallback(action):
        r=S.get(fallback,params={'fiat':FIAT,'asset':ASSET,'tradeType':action,'limit':40},headers={'Referer':'https://www.binance.com/'},timeout=12)
        r.raise_for_status()
        out=[]
        data=r.json().get('data') or {}
        for a in data.get('items') or []:
            m=a.get('advertiser') or {}
            price=num(a.get('price'))
            pays=[str(x) for x in (a.get('tradeMethods') or []) if x]
            out.append(Offer(
                'Binance',action,price,
                num(a.get('minTransAmount'))*price,
                num(a.get('maxTransAmount'))*price,
                str(m.get('nickName') or 'unknown'),
                rate(m.get('monthFinishRate') or m.get('positiveRate')),
                int(num(m.get('monthOrderCount'),0)) or None,
                pays,
                'official-public'
            ))
        return keep(out,action)

    try:
        b,s=parse_fallback('BUY'),parse_fallback('SELL')
        return {'exchange':'Binance','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · fallback feed','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'Binance','ok':False,'note':f'Binance P2P feed unavailable: {type(e).__name__}: {e}','buy':[],'sell':[]}

def bybit():
    if not eb('P2P_BYBIT_ENABLED','1'):
        return {'exchange':'Bybit','ok':False,'note':'вимкнено','buy':[],'sell':[]}

    # Якщо є ключі — пробуємо офіційний API. Якщо нема або він відмовив —
    # читаємо публічний веб-фід, який використовує P2P-сторінка Bybit.
    if BY_KEY and BY_SECRET:
        try:
            from pybit.unified_trading import HTTP
            api=HTTP(testnet=False,api_key=BY_KEY,api_secret=BY_SECRET)
            def get_auth(action):
                side='1' if action=='BUY' else '0'
                out=[]
                for page in range(1,MARKET_PAGES+1):
                    raw=api.get_online_ads(tokenId=ASSET,currencyId=FIAT,side=side,page=str(page),size='20')
                    items=(raw.get('result') or {}).get('items') or []
                    if not items: break
                    for a in items:
                        pref=a.get('tradingPreferenceSet') or {}
                        orders=int(num(a.get('recentOrderNum') or pref.get('orderFinishNumberDay30'),0)) or None
                        out.append(Offer('Bybit',action,num(a.get('price')),num(a.get('minAmount')),num(a.get('maxAmount')),str(a.get('nickName') or 'unknown'),rate(a.get('recentExecuteRate') or pref.get('completeRateDay30')),orders,[str(x) for x in a.get('payments') or []],'official-api'))
                    if len(items)<20: break
                return keep(out,action)
            b,s=get_auth('BUY'),get_auth('SELL')
            if b or s:
                return {'exchange':'Bybit','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · офіційний API','buy':b,'sell':s}
        except Exception:
            pass

    url='https://api2.bybit.com/fiat/otc/item/online'
    headers={'User-Agent':S.headers['User-Agent'],'Accept':'application/json','Content-Type':'application/json','Origin':'https://www.bybit.com','Referer':'https://www.bybit.com/'}
    def get_public(action):
        side='1' if action=='BUY' else '0'
        out=[]
        for page in range(1,MARKET_PAGES+1):
            payload={'userId':'','tokenId':ASSET,'currencyId':FIAT,'payment':[],'side':side,'size':'20','page':str(page),'amount':'','authMaker':False,'canTrade':False}
            r=S.post(url,json=payload,headers=headers,timeout=12); r.raise_for_status()
            items=(r.json().get('result') or {}).get('items') or []
            if not items: break
            for a in items:
                pref=a.get('tradingPreferenceSet') or {}
                orders=int(num(a.get('recentOrderNum') or pref.get('orderFinishNumberDay30'),0)) or None
                pays=[]
                for x in a.get('payments') or []:
                    if isinstance(x,dict): pays.append(str(x.get('paymentName') or x.get('paymentType') or ''))
                    elif x: pays.append(str(x))
                out.append(Offer('Bybit',action,num(a.get('price')),num(a.get('minAmount')),num(a.get('maxAmount')),str(a.get('nickName') or 'unknown'),rate(a.get('recentExecuteRate') or pref.get('completeRateDay30')),orders,[x for x in pays if x],'web-feed'))
            if len(items)<20: break
        return keep(out,action)
    try:
        b,s=get_public('BUY'),get_public('SELL')
        return {'exchange':'Bybit','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · публічний веб-фід','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'Bybit','ok':False,'note':f'публічний веб-фід недоступний: {type(e).__name__}: {e}','buy':[],'sell':[]}

def okx():
    # Публічний фід маркетплейсу OKX P2P — ключі не потрібні.
    url='https://www.okx.com/v3/c2c/tradingOrders/books'
    headers={'User-Agent':S.headers['User-Agent'],'Accept':'application/json','Referer':'https://www.okx.com/'}
    def get(action):
        side='sell' if action=='BUY' else 'buy'
        params={'quoteCurrency':FIAT.lower(),'baseCurrency':ASSET.lower(),'side':side,'paymentMethod':'all','userType':'all','showTrade':'false','showFollow':'false','showAlreadyTraded':'false','isAbleFilter':'true','receivingAds':'false'}
        r=S.get(url,params=params,headers=headers,timeout=12); r.raise_for_status()
        items=((r.json().get('data') or {}).get(side) or [])
        out=[]
        for a in items:
            pays=[]
            for p in a.get('paymentMethods') or []:
                if isinstance(p,str): pays.append(p)
                elif isinstance(p,dict): pays.append(str(p.get('paymentMethod') or p.get('name') or ''))
            out.append(Offer('OKX',action,num(a.get('price')),num(a.get('quoteMinAmountPerOrder')),num(a.get('quoteMaxAmountPerOrder')),str(a.get('nickName') or 'unknown'),rate(a.get('completedRate') or a.get('completionRate')),int(num(a.get('completedOrderQuantity') or a.get('orders'),0)) or None,[x for x in pays if x],'web-feed'))
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL')
        return {'exchange':'OKX','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · публічний веб-фід','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'OKX','ok':False,'note':f'публічний веб-фід недоступний: {type(e).__name__}: {e}','buy':[],'sell':[]}

def mexc():
    # Публічний P2P-фід MEXC — merchant API key для читання маркету не потрібен.
    coin_ids={'USDT':'128f589271cb4951b03e71e6323eb7be','BTC':'febc9973be4d4d53bb374476239eb219','ETH':'93c38b0169214f8689763ce9a63a73ff','USDC':'34309140878b4ae99f195ac091d49bab'}
    url='https://www.mexc.com/api/platform/p2p/api/market'
    headers={'User-Agent':S.headers['User-Agent'],'Accept':'application/json','Referer':'https://www.mexc.com/buy-crypto/p2p'}
    def get(action):
        trade_type='SELL' if action=='BUY' else 'BUY'
        out=[]
        for page in range(1,MARKET_PAGES+1):
            params={'adsType':'0','allowTrade':'true','amount':'','blockTrade':'false','certifiedMerchant':'false','coinId':coin_ids.get(ASSET,coin_ids['USDT']),'countryCode':'','currency':FIAT,'follow':'false','haveTrade':'false','page':str(page),'payMethod':'','tradeType':trade_type}
            r=S.get(url,params=params,headers=headers,timeout=12); r.raise_for_status()
            items=r.json().get('data') or []
            if not items: break
            for a in items:
                m=a.get('merchant') if isinstance(a.get('merchant'),dict) else {}
                pays=[x.strip() for x in str(a.get('payMethod') or '').split(',') if x.strip()]
                out.append(Offer('MEXC',action,num(a.get('price')),num(a.get('minTradeLimit')),num(a.get('maxTradeLimit')),str(m.get('nickName') or 'unknown'),rate(m.get('completionRate') or a.get('completionRate')),int(num(m.get('orderCount') or a.get('orderCount'),0)) or None,pays,'web-feed'))
            if len(items)<20: break
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL')
        return {'exchange':'MEXC','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · публічний веб-фід','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'MEXC','ok':False,'note':f'публічний веб-фід недоступний: {type(e).__name__}: {e}','buy':[],'sell':[]}

def kucoin():
    # Публічний KuCoin P2P endpoint — ключі не потрібні.
    url='https://www.kucoin.com/_api/otc/ad/list'
    headers={'User-Agent':S.headers['User-Agent'],'Accept':'application/json','Referer':'https://www.kucoin.com/otc/buy/USDT-UAH','x-site':'global'}
    def get(action):
        side='SELL' if action=='BUY' else 'BUY'
        out=[]
        for page in range(1,MARKET_PAGES+1):
            params={'status':'PUTUP','currency':ASSET,'legal':FIAT,'page':str(page),'pageSize':'20','side':side,'amount':'','payTypeCodes':'','sortCode':'PRICE','highQualityMerchant':'0','canDealOrder':'false','lang':'en_US'}
            r=S.get(url,params=params,headers=headers,timeout=12); r.raise_for_status()
            raw=r.json()
            if not raw.get('success'): raise RuntimeError(raw.get('msg') or raw.get('code'))
            items=raw.get('items') or []
            if not items: break
            for a in items:
                pays=[]
                for p in a.get('adPayTypes') or []:
                    if isinstance(p,dict): pays.append(str(p.get('payTypeNameEn') or p.get('payTypeCode') or ''))
                out.append(Offer('KuCoin',action,num(a.get('floatPrice') or a.get('premium')),num(a.get('limitMinQuote')),num(a.get('limitMaxQuote')),str(a.get('nickName') or 'unknown'),rate(a.get('dealOrderRate')),int(num(a.get('dealOrderNum'),0)) or None,[x for x in pays if x],'web-feed'))
            if len(items)<20: break
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL')
        return {'exchange':'KuCoin','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · публічний веб-фід','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'KuCoin','ok':False,'note':f'публічний веб-фід недоступний: {type(e).__name__}: {e}','buy':[],'sell':[]}

def htx():
    # Публічний HTX P2P endpoint. Для UAH код фіату = 45, USDT coinId = 2.
    url='https://www.htx.com/-/x/otc/v1/data/trade-market'
    headers={'User-Agent':S.headers['User-Agent'],'Accept':'application/json','Referer':'https://www.htx.com/'}
    fiat_ids={'UAH':'45','RUB':'11','EUR':'14','USD':'2','GBP':'12','BYN':'72','KZT':'57','UZS':'61','TRY':'23'}
    coin_ids={'BTC':'1','USDT':'2','ETH':'3'}
    def get(action):
        trade_type='sell' if action=='BUY' else 'buy'
        params={'coinId':coin_ids.get(ASSET,'2'),'currency':fiat_ids.get(FIAT,FIAT.lower()),'tradeType':trade_type,'currPage':'1','payMethod':'0','acceptOrder':'-1','country':'','blockType':'general','online':'1','range':'0','amount':'','onlyTradable':'false','isFollowed':'false'}
        r=S.get(url,params=params,headers=headers,timeout=12); r.raise_for_status()
        raw=r.json()
        if int(raw.get('code',0))!=200: raise RuntimeError(raw.get('message') or raw.get('code'))
        out=[]
        for a in raw.get('data') or []:
            pays=[str(x.get('name') or x.get('payMethodId')) for x in (a.get('payMethods') or []) if isinstance(x,dict)]
            out.append(Offer('HTX',action,num(a.get('price')),num(a.get('minTradeLimit')),num(a.get('maxTradeLimit')),str(a.get('userName') or 'unknown'),rate(a.get('orderCompleteRate')),int(num(a.get('totalTradeOrderCount') or a.get('tradeMonthTimes'),0)) or None,pays,'web-feed'))
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL')
        return {'exchange':'HTX','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · публічний веб-фід','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'HTX','ok':False,'note':f'публічний веб-фід недоступний: {type(e).__name__}: {e}','buy':[],'sell':[]}

def bitget():
    if not BITGET_KEY or not BITGET_SECRET or not BITGET_PASS:
        return {'exchange':'Bitget','ok':False,'note':'потрібні API key + secret + passphrase з правом UTA P2P read','buy':[],'sell':[]}
    base='https://api.bitget.com'; path='/api/v3/p2p/ad-list'
    def get(action):
        # Bitget side is the merchant ad direction. To BUY crypto from ads we need merchant SELL ads, and vice versa.
        side='sell' if action=='BUY' else 'buy'
        params={'token':ASSET,'fiat':FIAT,'side':side,'pageNum':'1','limit':'10'}
        qs=urlencode(sorted(params.items()))
        ts=str(int(time.time()*1000))
        msg=ts+'GET'+path+'?'+qs
        sign=base64.b64encode(hmac.new(BITGET_SECRET.encode(),msg.encode(),hashlib.sha256).digest()).decode()
        headers={'ACCESS-KEY':BITGET_KEY,'ACCESS-SIGN':sign,'ACCESS-TIMESTAMP':ts,'ACCESS-PASSPHRASE':BITGET_PASS,'locale':'en-US'}
        r=S.get(base+path,params=params,headers=headers,timeout=12); r.raise_for_status()
        raw=r.json()
        if str(raw.get('code'))!='00000': raise RuntimeError(raw.get('msg') or raw.get('code'))
        out=[]
        for a in raw.get('data') or []:
            pays=[str(x.get('payMethodName') or x.get('payMethodId')) for x in (a.get('payMethods') or []) if isinstance(x,dict)]
            out.append(Offer('Bitget',action,num(a.get('price')),num(a.get('minAmount')),num(a.get('maxAmount')),str(a.get('merchantName') or 'unknown'),rate(a.get('completedRate')),int(num(a.get('completedOrderNum'),0)) or None,pays,'official-api'))
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL'); return {'exchange':'Bitget','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж','buy':b,'sell':s}
    except Exception as e:return {'exchange':'Bitget','ok':False,'note':f'помилка API: {type(e).__name__}: {e}','buy':[],'sell':[]}

def gate():
    if not GATE_KEY or not GATE_SECRET:
        return {'exchange':'Gate','ok':False,'note':'потрібні API key + secret з доступом до P2P','buy':[],'sell':[]}
    host='https://api.gateio.ws'; prefix='/api/v4'; path='/p2p/merchant/books/ads_list'
    def get(action):
        # Gate trade_type describes the advertisement side. For our BUY we read sell ads.
        trade_type='sell' if action=='BUY' else 'buy'
        body=json.dumps({'asset':ASSET,'fiat_unit':FIAT,'trade_type':trade_type},separators=(',',':'))
        ts=str(int(time.time()))
        body_hash=hashlib.sha512(body.encode()).hexdigest()
        sign_string='POST\n'+prefix+path+'\n\n'+body_hash+'\n'+ts
        sign=hmac.new(GATE_SECRET.encode(),sign_string.encode(),hashlib.sha512).hexdigest()
        headers={'Accept':'application/json','Content-Type':'application/json','Timestamp':ts,'KEY':GATE_KEY,'SIGN':sign}
        r=S.post(host+prefix+path,headers=headers,data=body,timeout=12); r.raise_for_status()
        raw=r.json()
        data=raw.get('data') if isinstance(raw,dict) else raw
        items=(data.get('list') if isinstance(data,dict) else data) or []
        out=[]
        for a in items:
            price=num(a.get('price') or a.get('unit_price'))
            min_fiat=num(a.get('fiat_min_amount'))
            max_fiat=num(a.get('fiat_max_amount'))
            if not min_fiat and a.get('min_single_trans_amount'): min_fiat=num(a.get('min_single_trans_amount'))*price
            if not max_fiat and a.get('max_single_trans_amount'): max_fiat=num(a.get('max_single_trans_amount'))*price
            pays=[]
            for x in a.get('trade_methods') or []:
                if isinstance(x,dict): pays.append(str(x.get('trade_method_name') or x.get('identifier') or x.get('pay_type') or ''))
                elif x: pays.append(str(x))
            out.append(Offer('Gate',action,price,min_fiat,max_fiat,str(a.get('nick_name') or a.get('nickname') or 'unknown'),None,None,[x for x in pays if x],'official-api'))
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL'); return {'exchange':'Gate','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж','buy':b,'sell':s}
    except Exception as e:return {'exchange':'Gate','ok':False,'note':f'помилка API: {type(e).__name__}: {e}','buy':[],'sell':[]}

def lbank():
    # Публічний LBank P2P endpoint — ключі не потрібні.
    url='https://www.lbank.com/lbk-api/otc-trade-center/fiat/p2p/adv/advertisementList'
    headers={'User-Agent':S.headers['User-Agent'],'Accept':'application/json','Referer':'https://www.lbank.com/'}
    def get(action):
        # У веб-інтерфейсі tradeType=buy означає, що користувач купує USDT.
        trade_type='buy' if action=='BUY' else 'sell'
        params={'tradeType':trade_type,'assetCode':ASSET,'currencyCode':FIAT,'showOnlyPurchasable':'false','certifiedOnly':'false','isFollow':'false','pageNo':'1','pageSize':'20','sortByPrice':'0','sortByOrderCount':'0','sortByCompletionRate':'0'}
        r=S.get(url,params=params,headers=headers,timeout=12); r.raise_for_status()
        items=((r.json().get('data') or {}).get('resultList') or []); out=[]
        for a in items:
            # Відкидаємо крос-лістинг інших бірж і промо-ціни для нових користувачів.
            if str(a.get('source') or '').upper() not in {'','LBANK'}: continue
            if a.get('topTag') or a.get('eligibilityType'): continue
            price=num(a.get('price'))
            original=num(a.get('originalPrice'))
            if original and price and abs(original-price)/original>0.05: continue
            pays=[str(x.get('name') or x.get('code')) for x in (a.get('payMethods') or []) if isinstance(x,dict)]
            comp=rate(str(a.get('lastDaysTurnoverRate') or '').replace('%',''))
            orders=int(num(a.get('dealOrderTotal') or a.get('orderCnt'),0)) or None
            out.append(Offer('LBank',action,price,num(a.get('minAmount')),num(a.get('maxAmount')),str(a.get('nickName') or 'unknown'),comp,orders,pays,'web-feed'))
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL')
        return {'exchange':'LBank','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · публічний веб-фід','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'LBank','ok':False,'note':f'публічний веб-фід недоступний: {type(e).__name__}: {e}','buy':[],'sell':[]}

def toobit():
    # Публічний Toobit P2P endpoint — ключі не потрібні.
    url='https://bapi.toobit.com/bapi/v2/fiat/p2p/ad-list'
    headers={'User-Agent':S.headers['User-Agent'],'Accept':'application/json','Referer':'https://www.toobit.com/'}
    def get(action):
        params={'tradeType':action,'fiatCurrency':FIAT,'cryptoCurrency':ASSET,'pageNum':'1','pageSize':'20','order':'0'}
        r=S.get(url,params=params,headers=headers,timeout=12); r.raise_for_status()
        raw=r.json()
        if int(raw.get('code',0))!=200: raise RuntimeError(raw.get('msg') or raw.get('code'))
        out=[]
        for a in (raw.get('data') or {}).get('adList') or []:
            pays=[str(x.get('paymethodName') or x.get('paymethodId')) for x in (a.get('paymethodInfoList') or []) if isinstance(x,dict)]
            trades=int(num(a.get('tradeVolume'),0))
            comp=rate(a.get('completionRate')) if trades>0 else None
            orders=trades if trades>=10 else None
            out.append(Offer('Toobit',action,num(a.get('price')),num(a.get('minLimit')),num(a.get('maxLimit')),str(a.get('merchantNickname') or 'unknown'),comp,orders,pays,'web-feed'))
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL')
        return {'exchange':'Toobit','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · публічний веб-фід','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'Toobit','ok':False,'note':f'публічний веб-фід недоступний: {type(e).__name__}: {e}','buy':[],'sell':[]}

def weex():
    # Публічний WEEX P2P endpoint — ключі не потрібні.
    url='https://otc-gateway.weex.com/api/market'
    headers={'User-Agent':S.headers['User-Agent'],'Accept':'application/json','Referer':'https://www.weex.com/'}
    def get(action):
        trade_type='SELL' if action=='BUY' else 'BUY'
        out=[]
        for page in range(1,MARKET_PAGES+1):
            params={'allowTrade':'false','amount':'','blockTrade':'false','coinId':'2','countryCode':'','currency':FIAT,'follow':'false','haveTrade':'false','page':str(page),'payMethod':'','tradeType':trade_type}
            r=S.get(url,params=params,headers=headers,timeout=12); r.raise_for_status()
            raw=r.json()
            if int(raw.get('code',-1))!=0: raise RuntimeError(raw.get('msg') or raw.get('code'))
            items=raw.get('data') or []
            if not items: break
            for a in items:
                # Відкидаємо крос-лістинг MEXC та спеціальні promo/flash ads.
                if str(a.get('source') or '').upper() not in {'','WEEX'}: continue
                if a.get('tagAlias') or a.get('tags'): continue
                m=a.get('merchant') or {}; st=a.get('merchantStatistics') or {}
                pays=[x.strip() for x in str(a.get('payMethod') or '').split(',') if x.strip()]
                orders=int(num(st.get('doneLastMonthCount') or st.get('totalBuyCount') or st.get('totalSellCount'),0)) or None
                comp=rate(st.get('lastMonthCompleteRate') or st.get('completeRate'))
                out.append(Offer('WEEX',action,num(a.get('price')),num(a.get('minTradeLimit')),num(a.get('maxTradeLimit')),str(m.get('nickName') or 'unknown'),comp,orders,pays,'web-feed'))
            if len(items)<20: break
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL')
        return {'exchange':'WEEX','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · публічний веб-фід','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'WEEX','ok':False,'note':f'публічний веб-фід недоступний: {type(e).__name__}: {e}','buy':[],'sell':[]}

def bingx():
    # Публічний BingX P2P endpoint. Сайт додає короткоживучі anti-replay параметри;
    # якщо endpoint зміниться, біржа чесно піде в OFF замість вигаданих даних.
    url='https://api-app.qq-os.com/api/c2c/v3/advert/list'
    headers={'User-Agent':S.headers['User-Agent'],'Accept':'application/json','Content-Type':'application/json','Origin':'https://fiat.bingx.com','Referer':'https://fiat.bingx.com/'}
    def get(action):
        typ=1 if action=='BUY' else 2
        body={'type':typ,'fiat':FIAT,'asset':ASSET,'pageSize':20,'paymentMethodIds':[],'paymentTimeLimits':[],'sortType':0,'amount':'','pageId':1,'advertFilter':{'matchUserCondition':0,'noPaymentMethodVerification':0,'tradedWithMerchantOnly':0,'verifiedMerchantOnly':0}}
        # Спочатку беремо серверний timestamp, якщо він потрібен endpoint-у.
        r=S.post(url,json=body,headers=headers,timeout=12)
        raw=r.json()
        if int(raw.get('code',0))==100003 and raw.get('timestamp'):
            h=dict(headers); h['x-request-timestamp']=str(raw['timestamp'])
            r=S.post(url,json=body,headers=h,timeout=12); raw=r.json()
        if not r.ok or raw.get('success') is False: raise RuntimeError(raw.get('msg') or f'HTTP {r.status_code}')
        data=raw.get('data') or {}
        items=data.get('list') or data.get('items') or data.get('records') or []
        out=[]
        for a in items:
            adv=a.get('advert') if isinstance(a.get('advert'),dict) else a
            m=a.get('merchant') if isinstance(a.get('merchant'),dict) else a.get('advertiser') if isinstance(a.get('advertiser'),dict) else {}
            price=num(adv.get('price') or adv.get('unitPrice'))
            # Не беремо voucher/flash discount як звичайний арбітражний курс.
            original=num(adv.get('originalPrice') or adv.get('marketPrice'))
            if original and price and abs(original-price)/original>0.05: continue
            if adv.get('voucher') or adv.get('tagAlias') or adv.get('promotion'): continue
            pays=[]
            for p in adv.get('paymentMethods') or adv.get('payMethods') or []:
                if isinstance(p,dict): pays.append(str(p.get('name') or p.get('paymentName') or p.get('methodName') or ''))
                elif p: pays.append(str(p))
            out.append(Offer('BingX',action,price,num(adv.get('minAmount') or adv.get('minLimit')),num(adv.get('maxAmount') or adv.get('maxLimit')),str(m.get('nickName') or m.get('nickname') or adv.get('nickName') or 'unknown'),rate(m.get('completionRate') or m.get('finishRate')),int(num(m.get('tradeCount') or m.get('orders'),0)) or None,[x for x in pays if x],'web-feed'))
        return keep(out,action)
    try:
        b,s=get('BUY'),get('SELL')
        return {'exchange':'BingX','ok':True,'note':f'{len(b)} купівля / {len(s)} продаж · публічний веб-фід','buy':b,'sell':s}
    except Exception as e:
        return {'exchange':'BingX','ok':False,'note':f'публічний веб-фід недоступний: {type(e).__name__}: {e}','buy':[],'sell':[]}

def configured_exchange_ids():
    env=[x.strip().lower() for x in os.getenv('P2P_EXCHANGES','').split(',') if x.strip()]
    if env:return env
    try:
        raw=json.loads(EXCHANGES_FILE.read_text(encoding='utf-8'))
        return [str(x.get('id','')).lower() for x in raw.get('exchanges',[]) if x.get('enabled',True) and x.get('id')]
    except Exception:
        return ['binance','bybit']

def provider_for(exchange_id):
    adapters={'binance':binance,'bybit':bybit,'okx':okx,'kucoin':kucoin,'mexc':mexc,'weex':weex}
    fn=adapters.get(str(exchange_id).lower())
    if not fn:return {'exchange':str(exchange_id).upper(),'ok':False,'note':'є пряме P2P-посилання; автоматичне сканування для цієї біржі ще не підключено','buy':[],'sell':[]}
    return fn()

def offer_risk(o):
    r=16 if o.source=='web-feed' else 0; why=[]
    if o.source=='web-feed':why.append(o.exchange+': web feed may change')
    if o.completion is None:r+=8;why.append(o.exchange+': completion unknown')
    elif o.completion<95:r+=10;why.append(f'{o.exchange}: completion {o.completion:.1f}%')
    if o.orders is None:r+=5
    elif o.orders<30:r+=9;why.append(f'{o.exchange}: only {o.orders} recent orders')
    if not o.payments:r+=4
    return r,why

def payment_key(x):
    s=str(x or '').strip().lower()
    aliases=[
        ('monobank','monobank'),('mono bank','monobank'),
        ('privatbank','privatbank'),('privat bank','privatbank'),
        ('pumb','pumb'),('пумб','pumb'),
        ('a-bank','abank'),('abank','abank'),('a bank','abank'),
        ('otp','otp'),('oschad','oschad'),('ощад','oschad'),
        ('raiffeisen','raiffeisen'),('райффайзен','raiffeisen'),
        ('sense','sense'),('izibank','izibank'),('izi bank','izibank'),
        ('sportbank','sportbank'),('universal','universal')
    ]
    for needle,key in aliases:
        if needle in s:return key
    return ''

def payment_match(a,b):
    ka={payment_key(x) for x in (a or []) if payment_key(x)}
    kb={payment_key(x) for x in (b or []) if payment_key(x)}
    if ka and kb:
        common=sorted(ka&kb)
        return bool(common),common,True
    return True,sorted(ka&kb),False

def routes(providers):
    buys=[o for p in providers if p['ok'] for o in p['buy']]; sells=[o for p in providers if p['ok'] for o in p['sell']]; out=[]
    for b in buys:
      for s in sells:
        pay_ok,common_payments,pay_known=payment_match(b.payments,s.payments)
        if not pay_ok: continue
        same=b.exchange==s.exchange; transfer_fee=0.0 if same else XFER
        qty=CAPITAL/b.price; gross=(s.price/b.price-1)*100; safety=CAPITAL*BUFFER/100
        net=(max(0,qty-transfer_fee)*s.price)-CAPITAL-safety; pref=(qty*s.price)-CAPITAL-safety; rb,wb=offer_risk(b); rs,ws=offer_risk(s); risk=max(rb,rs); why=wb+ws
        if same: why=['same-exchange route: no modeled crypto transfer fee']+why
        if pay_known and common_payments:
            why.append('common payment: '+', '.join(common_payments))
        elif not pay_known:
            risk+=6;why.append('payment compatibility not fully verified')
        drag=(transfer_fee*b.price/CAPITAL*100) if CAPITAL else 0
        if drag>.7:risk+=10;why.append(f'transfer drag {drag:.2f}%')
        abnormal=gross>REVIEW_SPREAD
        if abnormal:
            risk+=20;why.append(f'unusually large spread > {REVIEW_SPREAD:.2f}% — manual verification required')
        elif gross>1.5:
            risk+=8;why.append('large spread — re-check freshness')
        risk=min(100,risk); netpct=net/CAPITAL*100; prefpct=pref/CAPITAL*100
        if netpct>=MIN_NET and abnormal:
            verdict='REVIEW'
        elif netpct>=MIN_NET and risk<=MAX_RISK:
            verdict='ALERT'
        elif prefpct>=MIN_NET:
            verdict='PREFUNDED_ONLY'
        else:
            verdict='DROP'
        out.append({'buy_exchange':b.exchange,'sell_exchange':s.exchange,'route_type':'INTRA' if same else 'CROSS','buy_price':round(b.price,4),'sell_price':round(s.price,4),'gross_spread_pct':round(gross,3),'net_profit_fiat':round(net,2),'net_pct':round(netpct,3),'prefunded_net_pct':round(prefpct,3),'risk_score':risk,'verdict':verdict,'buy_merchant':b.merchant,'sell_merchant':s.merchant,'buy_completion_pct':b.completion,'sell_completion_pct':s.completion,'buy_payments':b.payments,'sell_payments':s.payments,'common_payments':common_payments,'payment_verified':pay_known and bool(common_payments),'reasons':why[:7]})
    priority={'ALERT':3,'REVIEW':2,'PREFUNDED_ONLY':1,'DROP':0}
    ranked=sorted(out,key=lambda x:(priority.get(x['verdict'],0),x['net_pct'],-x['risk_score']),reverse=True)
    seen=set(); unique=[]
    for x in ranked:
        key=(x['buy_exchange'],x['sell_exchange'],x['buy_merchant'],x['sell_merchant'],round(x['buy_price'],2),round(x['sell_price'],2))
        if key in seen: continue
        seen.add(key); unique.append(x)
    return unique

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
    e=str(exchange or '').lower(); a=str(action).upper()
    try:
        raw=json.loads(EXCHANGES_FILE.read_text(encoding='utf-8'))
        for x in raw.get('exchanges',[]):
            if str(x.get('id','')).lower()==e or str(x.get('name','')).lower()==e:
                return str(x.get('sell_url') if a=='SELL' else x.get('buy_url') or x.get('sell_url') or '')
    except Exception:pass
    if e=='binance':return f"https://p2p.binance.com/en/trade/all-payments/{ASSET}?fiat={FIAT}"
    if e=='bybit':return "https://www.bybit.com/fiat/trade/otc/"
    return ""

def telegram_keyboard(r):
    row=[]
    bu=exchange_url(r.get('buy_exchange'),'BUY'); su=exchange_url(r.get('sell_exchange'),'SELL')
    if bu:row.append({'text':f"🟢 КУПИТИ · {r.get('buy_exchange','')}",'url':bu})
    if su:row.append({'text':f"🔴 ПРОДАТИ · {r.get('sell_exchange','')}",'url':su})
    kb=[]
    if row:kb.append(row)
    if DASHBOARD_URL:kb.append([{'text':'📊 Відкрити радар','url':DASHBOARD_URL}])
    kb.append([{'text':'🔗 Я перевірив маршрут','callback_data':'p2p_route_checked'},{'text':'✅ Цикл завершено','callback_data':'p2p_cycle_done'}])
    kb.append([{'text':'⏸ Пауза сповіщень','callback_data':'p2p_pause'},{'text':'📋 Статус','callback_data':'p2p_status'}])
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
    guard={'OK':'НОРМА','WARN':'ПОПЕРЕДЖЕННЯ','STOP':'СТОП'}.get(bg['level'],bg['level'])
    return (f"🐭 MYSHKA P2P — СТАТУС\nЗахист банківських переказів: {guard}\n"
            f"Підтверджені цикли: {bg['confirmed_cycles']}\n"
            f"Підтверджені перекази: {bg['confirmed_transfers']}/{bg['max_transfers']}\n"
            f"Перевірок маршрутів: {int(b.get('route_checks',0))} (попередження після {TG_CONFIRM_WARN})\n"
            f"Сповіщень сьогодні: {bg['alerts_sent']}/{BANK_ALERT_MAX}\n"
            f"Пауза після циклу: {bg['cooldown_remaining_seconds']//60} хв\n"
            f"Сповіщення на паузі: {'ТАК' if bg['paused'] else 'НІ'}")

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
                        b,bg=bank_apply('cycle-done');callback_answer(qid,f"Цикл #{bg['confirmed_cycles']} зараховано · захист: {bg['level']}",bg['level']!='OK')
                    elif data=='p2p_pause':
                        bank_apply('pause');callback_answer(qid,'P2P-сповіщення поставлено на паузу.',True)
                    elif data=='p2p_status':
                        callback_answer(qid,'Статус надіслано');telegram(telegram_status_text())
                    continue
                m=u.get('message') or {};chat=str((m.get('chat') or {}).get('id',''))
                if chat!=str(TG_CHAT):continue
                cmd=str(m.get('text') or '').strip().lower().split()[0] if m.get('text') else ''
                if cmd in {'/p2p','/p2p_status','/status'}:telegram(telegram_status_text())
                elif cmd in {'/p2p_pause','/pause'}:bank_apply('pause');telegram('⏸ MYSHKA P2P: сповіщення поставлено на паузу.')
                elif cmd in {'/p2p_resume','/resume'}:bank_apply('resume');telegram('▶️ MYSHKA P2P: сповіщення відновлено.')
                elif cmd in {'/p2p_done','/done'}:
                    _,bg=bank_apply('cycle-done');telegram(f"✅ Цикл #{bg['confirmed_cycles']} зараховано · захист: {bg['level']}.")
                elif cmd in {'/p2p_help','/help'}:telegram("Команди MYSHKA P2P:\n/p2p_status — статус\n/p2p_pause — пауза\n/p2p_resume — продовжити\n/p2p_done — цикл завершено")
        except Exception as e:
            print('TELEGRAM CONTROL:',e,flush=True);time.sleep(4)

def tg_text(r,ts,bg):
    kind='НА ОДНІЙ БІРЖІ' if r.get('route_type')=='INTRA' else 'МІЖ БІРЖАМИ'
    verdict={'ALERT':'Є ВАРІАНТ','PREFUNDED_ONLY':'ЛИШЕ З ГОТОВИМ БАЛАНСОМ','DROP':'НЕ ВИГІДНО'}.get(r.get('verdict'),r.get('verdict'))
    return f"🐭 MYSHKA P2P РАДАР\n{verdict} · {kind} · {ASSET}/{FIAT}\nКУПИТИ {r['buy_exchange']}: {r['buy_price']:.4f}\nПРОДАТИ {r['sell_exchange']}: {r['sell_price']:.4f}\nСпред {r['gross_spread_pct']:+.2f}%\nЧистими {r['net_pct']:+.2f}% ≈ {r['net_profit_fiat']:+.2f} {FIAT}\nБез переказу {r['prefunded_net_pct']:+.2f}%\nРизик {r['risk_score']}/100\nЗахист переказів: {bg['level']} · {bg['confirmed_transfers']}/{bg['max_transfers']} сьогодні\n{ts}\nВідкрий кнопки «КУПИТИ» і «ПРОДАТИ», звір живі оголошення та тільки тоді вирішуй, чи робити операцію."
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
    ts=datetime.now(KYIV).isoformat(timespec='seconds'); ids=configured_exchange_ids(); ps=[provider_for(x) for x in ids]; rs=routes(ps); top=rs[0] if rs else None
    b=bank_state(); bg=bank_guard(b)
    if bg['paused'] and top and top['verdict']=='ALERT':
        top=dict(top); top['verdict']='PAUSE_BANK_GUARD'; top['reasons']=([bg['reason']] if bg['reason'] else ['Bank Guard paused actionable alerts'])+list(top.get('reasons') or [])
    elif bg['cooldown_remaining_seconds']>0 and top and top['verdict']=='ALERT':
        top=dict(top); top['verdict']='COOLDOWN'; top['reasons']=[f"Bank Guard cooldown {bg['cooldown_remaining_seconds']//60+1} min remaining"]+list(top.get('reasons') or [])
    snap={'version':'MYSHKA_P2P_RADAR_V4','scanned_at':ts,'fiat':FIAT,'asset':ASSET,'capital_fiat':CAPITAL,'mode':'ХМАРНИЙ СКАНЕР 24/7','bank_guard':bg,'providers':[public_provider(x) for x in ps],'routes':rs[:25],'top_route':top,'route_count':len(rs),'shown_routes':min(25,len(rs)),'alerts':sum(x['verdict']=='ALERT' for x in rs),'review_count':sum(x['verdict']=='REVIEW' for x in rs),'review_spread_pct':REVIEW_SPREAD,'market_pages':MARKET_PAGES,'offers_per_side':KEEP_PER_SIDE}
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
