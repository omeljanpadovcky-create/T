/* Cloud JEV screenshot analyzer (Vercel Node.js). Secrets never reach GitHub Pages. */
import { timingSafeEqual } from 'node:crypto';

const ALLOWED_ORIGINS = new Set([
  'https://omeljanpadovcky-create.github.io',
  'http://127.0.0.1:18765',
  'http://localhost:18765'
]);
const TIMEFRAMES = { '15s': 15, '30s': 30, '1m': 60, '5m': 300, '15m': 900, '30m': 1800, '1h': 3600, '4h': 14400 };
const EXPIRIES = new Set([30, 60, 300]);
const MAX_IMAGE_BYTES = 2 * 1024 * 1024;
function modelAndProvider() {
  // When a direct Gemini key is configured, prefer Google's documented
  // Flash-Lite free-tier vision path. Never silently fall back to a billable API.
  const geminiKey = (process.env.GEMINI_API_KEY || '').trim();
  if (geminiKey) return {provider:'gemini',model:process.env.JEV_CLOUD_MODEL || 'gemini-2.5-flash-lite',key:geminiKey};
  const apinexKey = (process.env.APINEX_API_KEY || '').trim();
  if (apinexKey) return {provider:'apinex',model:process.env.JEV_APINEX_MODEL || 'gemini-3.8-flash',key:apinexKey};
  return null;
}

function authOk(req) {
  const expected = process.env.JEV_ACCESS_TOKEN || '';
  const actual = req.headers['x-jev-access'] || '';
  if (typeof actual !== 'string' || expected.length < 24 || actual.length !== expected.length) return false;
  return timingSafeEqual(Buffer.from(actual), Buffer.from(expected));
}
function headers(req, res) {
  const origin = req.headers.origin;
  if (ALLOWED_ORIGINS.has(origin)) res.setHeader('Access-Control-Allow-Origin', origin);
  res.setHeader('Vary', 'Origin');
  res.setHeader('Access-Control-Allow-Methods', 'POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type,X-JEV-Access');
  res.setHeader('Cache-Control', 'no-store');
}
function skip(reason = 'Ринкові дані не підтверджені — краще утриматися.') {
  return {direction:'СТОП',action:'SKIP',test_expiry_seconds:null,horizon_minutes:null,
    chart_timeframe:'unknown',timeframe_source:'unknown',reason,risk:'Невизначеність або недостатньо даних.',
    market_verified:false,signal_validated:false,expiry_validated:false};
}
export function parseVision(raw, requested='auto', market=null) {
  const base=skip();
  let data;
  try { data=JSON.parse(String(raw||'').trim().replace(/^```(?:json)?\s*/i,'').replace(/\s*```$/,'').trim()); }
  catch { return base; }
  if(!data||typeof data!=='object'||data.readable!==true||
    !['ВГОРУ','ВНИЗ','СТОП','НЕВИЗНАЧЕНО'].includes(data.direction))return base;
  const manual=Object.hasOwn(TIMEFRAMES,requested);
  const tf=manual?requested:Object.hasOwn(TIMEFRAMES,data.chart_timeframe)?data.chart_timeframe:'unknown';
  const reason=typeof data.evidence==='string'?data.evidence.trim().slice(0,320):'';
  const risk=typeof data.risk==='string'?data.risk.trim().slice(0,240):'';
  const direction=data.direction==='НЕВИЗНАЧЕНО'?'СТОП':data.direction;
  const out={...base,direction:'СТОП',chart_timeframe:tf,timeframe_source:manual?'user':tf==='unknown'?'unknown':'model',
    reason:reason||base.reason,risk:risk||base.risk,market_verified:!!market,model_direction:direction};
  if(!market||tf==='unknown'||direction==='СТОП'||reason.length<25||risk.length<12)return out;
  const horizon=Number(data.horizon_minutes);
  if(![5,15,60].includes(horizon)||horizon*60<TIMEFRAMES[tf])return out;
  const requestedSide=direction==='ВГОРУ'?'up':'down';
  const votes=market.intervals.map(x=>x.regime);
  if(votes.filter(x=>x===requestedSide).length<2||
     votes.filter(x=>x!==requestedSide&&x!=='range').length>0)return {...out,reason:'Сигнал не узгоджується з кількома таймфреймами Bybit. '+out.reason};
  return {...out,direction,action:direction==='ВГОРУ'?'BUY':'SELL',
    horizon_minutes:horizon,signal_validated:false,expiry_validated:false};
}
function imageType(bytes) {
  if (bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return 'image/png';
  if (bytes.length >= 3 && bytes[0]===255 && bytes[1]===216 && bytes[2]===255) return 'image/jpeg';
  if (bytes.length >= 12 && bytes.toString('ascii',0,4)==='RIFF' &&
      bytes.toString('ascii',8,12)==='WEBP') return 'image/webp';
  return null;
}

const TRACKED=new Set(['BTCUSDT','ETHUSDT','SOLUSDT']);
async function getMarketContext(symbol,category) {
  if(typeof symbol!=='string'||!TRACKED.has(symbol)||!['spot','linear'].includes(category))
    throw new Error('Вибери BTC, ETH або SOL і правильний ринок Bybit.');
  const intervals=await Promise.all([5,15,60].map(async minutes=>{
    const url='https://api.bybit.com/v5/market/kline?category='+category+
      '&symbol='+encodeURIComponent(symbol)+'&interval='+minutes+'&limit=80';
    const response=await fetch(url,{signal:AbortSignal.timeout(7000),headers:{Accept:'application/json'}});
    if(!response.ok)throw new Error('Bybit HTTP '+response.status);
    const data=await response.json();
    if(data?.retCode!==0||!Array.isArray(data?.result?.list)||
       data.result.symbol&&data.result.symbol!==symbol)throw new Error('Помилка підтвердження Bybit OHLCV.');
    const now=Date.now(),step=minutes*60000;
    const rows=data.result.list.map(r=>({time:Number(r[0]),open:Number(r[1]),high:Number(r[2]),
      low:Number(r[3]),close:Number(r[4]),volume:Number(r[5])}))
      .filter(r=>Object.values(r).every(Number.isFinite)&&r.time>0&&r.close>0&&r.low>0&&
        r.high>=Math.max(r.open,r.close,r.low)&&r.low<=Math.min(r.open,r.close)&&r.time+step<=now-1000)
      .sort((a,b)=>a.time-b.time);
    if(rows.length<35)throw new Error('Недостатньо завершених свічок.');
    const recent=rows.slice(-35);
    if(recent.some((r,i)=>i>0&&r.time-recent[i-1].time!==step))
      throw new Error('В історії Bybit є пропуски.');
    const last=rows.at(-1);
    if(now-(last.time+step)>step*2.2)throw new Error('Застарілі котирування Bybit.');
    const closes=rows.map(x=>x.close);
    function ema(n){let a=closes.slice(0,n).reduce((s,x)=>s+x,0)/n;
      for(let k=n;k<closes.length;k++)a+=(2/(n+1))*(closes[k]-a);return a;}
    const e9=ema(9),e21=ema(21);
    let up=0,down=0,tr=0;
    for(let i=rows.length-14;i<rows.length;i++){
      const d=rows[i].close-rows[i-1].close;
      up+=Math.max(d,0);down+=Math.max(-d,0);
      tr+=Math.max(rows[i].high-rows[i].low,
        Math.abs(rows[i].high-rows[i-1].close),Math.abs(rows[i].low-rows[i-1].close));
    }
    const rsi=up===0&&down===0?50:down===0?100:100-100/(1+up/down);
    const atr=tr/14, momentum=last.close-rows.at(-6).close;
    const regime=e9-e21>atr*.15&&momentum>atr*.3?'up':
      e21-e9>atr*.15&&momentum< -atr*.3?'down':'range';
    const v20=rows.slice(-21,-1).reduce((s,x)=>s+x.volume,0)/20;
    const window=rows.slice(-20);
    return {minutes,closedAt:new Date(last.time+step).toISOString(),
      lastClose:Number(last.close.toPrecision(8)),ema9:Number(e9.toPrecision(8)),
      ema21:Number(e21.toPrecision(8)),rsi14:Number(rsi.toFixed(2)),
      atrPct:Number((100*atr/last.close).toFixed(3)),
      momentum5Pct:Number((100*momentum/rows.at(-6).close).toFixed(3)),
      volumeRatio:v20>0?Number((last.volume/v20).toFixed(2)):null,
      support:Number(Math.min(...window.map(x=>x.low)).toPrecision(8)),
      resistance:Number(Math.max(...window.map(x=>x.high)).toPrecision(8)),
      regime};
  }));
  return {symbol,category,source:'Bybit V5 /v5/market/kline',
    verifiedAt:new Date().toISOString(),intervals};
}

const SYSTEM = `Ти JEV — дослідницький аналітик криптографіків, не оракул.
Дай конкретну, але НЕ гарантовану гіпотезу майбутнього руху.
Твоє завдання: прочитати свічки на фото, перевірити, чи збігаються актив,
ринок і таймфрейм з підтвердженими закритими свічками Bybit, врахувати
EMA 9/21, RSI, імпульс, волатильність, підтримку/опір, обсяг на 5/15/60 хв.
Якщо фото з OTC/іншої біржі, не видно активу, тренди суперечать один одному,
не вистачає даних або немає чіткого аргументу — дай СТОП.
Не трактуй уже намальований рух як доказ майбутнього.
Відповідай ТІЛЬКИ JSON:
{"readable":true/false,"direction":"ВГОРУ"|"ВНИЗ"|"СТОП",
"chart_timeframe":"15s"|"30s"|"1m"|"5m"|"15m"|"30m"|"1h"|"4h"|"unknown",
"horizon_minutes":5|15|60|null,
"evidence":"конкретні факти фото та підтверджених Bybit даних, без вигадок",
"risk":"конкретна причина, через яку прогноз може бути хибним"}.
Горизонт прогнозу має бути не коротшим за одну свічку фото.
Не вигадуй відсоток упевненості, прибуток, рівні ціни чи тривалість руху,
якщо даних для них немає. Жодних імперативних наказів торгувати.`;
export default async function handler(req, res) {
  headers(req,res);
  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'POST') return res.status(405).json({error:'POST only'});
  if (!ALLOWED_ORIGINS.has(req.headers.origin)) return res.status(403).json({error:'Недозволений сайт.'});
  const provider = modelAndProvider();
  if (!provider || !process.env.JEV_ACCESS_TOKEN) return res.status(503).json({error:'Хмарний AI ще не налаштовано (змінні APINEX_API_KEY або GEMINI_API_KEY та JEV_ACCESS_TOKEN потрібні на сервері).'});
  if (!authOk(req)) return res.status(401).json({error:'Неправильний код доступу до JEV.'});
  const body = req.body || {};
  if (!body || typeof body !== 'object' || Array.isArray(body)) return res.status(400).json({error:'Invalid JSON body'});
  const timeframe = body.chart_timeframe ?? 'auto';
  if (timeframe !== 'auto' && !Object.hasOwn(TIMEFRAMES,timeframe)) return res.status(400).json({error:'Невідомий таймфрейм.'});
  const image = body.image;
  if (typeof image !== 'string' || image.length < 20 || image.length > Math.ceil(MAX_IMAGE_BYTES*4/3)+8 ||
      !/^[A-Za-z0-9+/]+={0,2}$/.test(image)) return res.status(413).json({error:'Фото має бути JPG/PNG/WebP до 2 МБ.'});
  const bytes = Buffer.from(image,'base64');
  const mime = bytes.length <= MAX_IMAGE_BYTES ? imageType(bytes) : null;
  if (!mime) return res.status(400).json({error:'Непідтримуваний або завеликий файл.'});
  try {
    let market;
    try { market=await getMarketContext(body.market_symbol,body.market_category); }
    catch(err) { return res.status(200).json({...skip('СТОП: '+String(err?.message||'Bybit недоступний').slice(0,180)),
      source:'market_unavailable',mode:'research_only'}); }
    const prompt='Вибраний користувачем ринок: '+market.symbol+' '+market.category+
      '. Перевір напис пари/біржі на фото; якщо не збігається або її не видно — СТОП. '+
      'Таймфрейм фото: '+timeframe+'. Верифіковані сервером ЗАКРИТІ свічки Bybit: '+
      JSON.stringify(market)+'. Висновок стосується ТІЛЬКИ цього активу. '+
      'Напрям — гіпотеза, не гарантія і не команда на угоду.';
    const isApinex = provider.provider === 'apinex';
    const url = isApinex
      ? 'https://api.apinex.bond/v1/chat/completions'
      : 'https://generativelanguage.googleapis.com/v1beta/models/' +
        encodeURIComponent(provider.model) + ':generateContent';
    const headers = isApinex
      ? {'Content-Type':'application/json',Authorization:'Bearer ' + provider.key}
      : {'Content-Type':'application/json','x-goog-api-key':provider.key};
    const payload = isApinex ? {
      model:provider.model,temperature:0,max_tokens:450,stream:false,
      messages:[
        {role:'system',content:SYSTEM},
        {role:'user',content:[
          {type:'text',text:prompt},
          {type:'image_url',image_url:{url:'data:' + mime + ';base64,' + image}}
        ]}
      ]
    } : {
      systemInstruction:{parts:[{text:SYSTEM}]},
      contents:[{role:'user',parts:[{text:prompt},{inlineData:{mimeType:mime,data:image}}]}],
      generationConfig:{temperature:0,responseMimeType:'application/json',maxOutputTokens:450}
    };
    const response = await fetch(url, {
      method:'POST',headers,body:JSON.stringify(payload),
      signal:AbortSignal.timeout(25000)
    });
    if (!response.ok) return res.status(response.status===402?402:response.status===429?429:502).json({
      error:response.status===429?'Ліміт запитів хмарного AI. Спробуй пізніше.':
        response.status===401?'APInex або Gemini відхилив API-ключ.':
        'Хмарний AI не зміг обробити фото (HTTP ' + response.status + ').'});
    const data = await response.json();
    const content = data?.choices?.[0]?.message?.content;
    const raw = isApinex
      ? (typeof content==='string' ? content :
          Array.isArray(content) ? content.map(p=>typeof p==='string'?p:(p?.text||'')).join('') : '')
      : (data?.candidates?.[0]?.content?.parts?.map(p=>p.text||'').join('') || '');
    const parsed = parseVision(raw,timeframe,market);
    return res.status(200).json({...parsed,analysis:parsed.direction,model:provider.model,
      source:isApinex?'cloud_apinex':'cloud_gemini',provider:provider.provider,
      market_verified:true,market_symbol:market.symbol,market_category:market.category,
      market_context:market,mode:'research_hypothesis',verified_quotes:true});
  } catch (err) {
    return res.status(504).json({error:err?.name==='TimeoutError'?'Хмарний AI не відповів за 25 секунд.':'Не вдалося зв’язатися з AI-провайдером.'});
  }
}
