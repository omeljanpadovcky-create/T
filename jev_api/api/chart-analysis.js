/* Cloud JEV screenshot analyzer (Vercel Node.js). Secrets never reach GitHub Pages. */
import { timingSafeEqual } from 'node:crypto';

const ALLOWED_ORIGINS = new Set([
  'https://omeljanpadovcky-create.github.io',
  'http://127.0.0.1:18765',
  'http://localhost:18765'
]);
const TIMEFRAMES = { '15s': 15, '30s': 30, '1m': 60, '5m': 300 };
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
function skip(reason = 'Недостатньо даних для демо-гіпотези.') {
  return {direction:'НЕВИЗНАЧЕНО', action:'SKIP', test_expiry_seconds:null,
    chart_timeframe:'unknown', timeframe_source:'unknown', reason,
    signal_validated:false, expiry_validated:false};
}
export function parseVision(raw, requested = 'auto') {
  const base = skip();
  let data;
  try {
    data = JSON.parse(String(raw || '').trim().replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/, ''));
  } catch { return base; }
  if (!data || typeof data !== 'object' || data.readable !== true ||
      !['ВГОРУ','ВНИЗ','НЕВИЗНАЧЕНО'].includes(data.direction)) return base;
  const manual = Object.hasOwn(TIMEFRAMES, requested);
  const tf = manual ? requested : Object.hasOwn(TIMEFRAMES, data.chart_timeframe) ? data.chart_timeframe : 'unknown';
  const reason = typeof data.evidence === 'string' ? data.evidence.trim().slice(0,180) : '';
  const out = {...base, direction:data.direction, chart_timeframe:tf,
    timeframe_source:manual?'user':tf==='unknown'?'unknown':'model',
    reason:reason || base.reason};
  const expiry = data.test_expiry_seconds;
  if (out.direction !== 'НЕВИЗНАЧЕНО' && tf !== 'unknown' &&
      Number.isInteger(expiry) && EXPIRIES.has(expiry) && expiry >= TIMEFRAMES[tf] &&
      reason.length >= 12) {
    out.action = out.direction === 'ВГОРУ' ? 'BUY' : 'SELL';
    out.test_expiry_seconds = expiry;
  }
  return out;
}
function imageType(bytes) {
  if (bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return 'image/png';
  if (bytes.length >= 3 && bytes[0]===255 && bytes[1]===216 && bytes[2]===255) return 'image/jpeg';
  if (bytes.length >= 12 && bytes.toString('ascii',0,4)==='RIFF' &&
      bytes.toString('ascii',8,12)==='WEBP') return 'image/webp';
  return null;
}
const SYSTEM = `Ти JEV, асистент для дослідження ДЕМО-графіків.
Оціни лише видимий рух, не прогнозуй гарантованих результатів.
Розрізняй таймфрейм ОДНІЄЇ СВІЧКИ і час закриття BUY/SELL.
Таймер 00:01:00 біля кнопок — це час угоди, не таймфрейм.
Відповідай тільки JSON з ключами:
direction ("ВГОРУ", "ВНИЗ", "НЕВИЗНАЧЕНО"),
readable (boolean), chart_timeframe ("15s", "30s", "1m", "5m", "unknown"),
test_expiry_seconds (30, 60, 300 або null), evidence (короткий факт зі скріншота).
Якщо свічок не видно, таймфрейм невідомий, графік змішаний, або немає
зрозумілої структури — direction "НЕВИЗНАЧЕНО", readable false, expiry null.
Час експірації — лише неперевірена гіпотеза для демо, не сигнал торгувати.
Не вигадуй цін, індикаторів, прибутків або точності.`;

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
    const prompt = 'Таймфрейм свічки від користувача: ' + timeframe +
      '. Якщо auto, визначай тільки за підписом на самому графіку. Демо-експірація 30, 60 або 300 секунд або null.';
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
    const parsed = parseVision(raw,timeframe);
    return res.status(200).json({...parsed,analysis:parsed.direction,model:provider.model,
      source:isApinex?'cloud_apinex':'cloud_gemini',provider:provider.provider,
      mode:'demo_hypothesis',verified_quotes:false});
  } catch (err) {
    return res.status(504).json({error:err?.name==='TimeoutError'?'Хмарний AI не відповів за 25 секунд.':'Не вдалося зв’язатися з AI-провайдером.'});
  }
}
