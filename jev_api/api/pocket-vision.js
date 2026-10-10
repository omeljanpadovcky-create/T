/* Pocket Option screenshot research endpoint. NO broker API, market verification or orders. */
import {timingSafeEqual} from 'node:crypto';
const ORIGINS=new Set(['https://omeljanpadovcky-create.github.io','http://127.0.0.1:18765','http://localhost:18765']);
const MAX_BYTES=2*1024*1024;
const TF=new Set([15,30,60,300,900]),EXPIRIES=new Set([30,60,180,300]);
const stop=(reason,risk='Невідомий майбутній рух, OTC-котирування не перевірені незалежним джерелом.')=>({
  mode:'screenshot_hypothesis',direction:'STOP',reason,risk,signal_validated:false,
  broker_verified:false,quotes_verified:false,orders_enabled:false,probability:null
});
function cors(req,res){
  if(ORIGINS.has(req.headers.origin))res.setHeader('Access-Control-Allow-Origin',req.headers.origin);
  res.setHeader('Vary','Origin');
  res.setHeader('Access-Control-Allow-Methods','OPTIONS,POST');
  res.setHeader('Access-Control-Allow-Headers','Content-Type,X-JEV-Access');
  res.setHeader('Cache-Control','no-store, private');
}
function validAccess(req){
  const expected=process.env.JEV_ACCESS_TOKEN||'',actual=req.headers['x-jev-access'];
  return typeof actual==='string'&&Buffer.byteLength(expected)>=24&&
    Buffer.byteLength(expected)===Buffer.byteLength(actual)&&
    timingSafeEqual(Buffer.from(expected),Buffer.from(actual));
}
function provider(){
  const gemini=String(process.env.GEMINI_API_KEY||'').trim();
  if(gemini)return{name:'gemini',model:process.env.JEV_CLOUD_MODEL||'gemini-2.5-flash-lite',key:gemini};
  const apinex=String(process.env.APINEX_API_KEY||'').trim();
  if(apinex)return{name:'apinex',model:process.env.JEV_APINEX_MODEL||'gemini-3.8-flash',key:apinex};
  return null;
}
function imageType(bytes){
  if(bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])))return 'image/png';
  if(bytes.length>3&&bytes[0]===255&&bytes[1]===216&&bytes[2]===255)return 'image/jpeg';
  if(bytes.toString('ascii',0,4)==='RIFF'&&bytes.toString('ascii',8,12)==='WEBP')return 'image/webp';
  return null;
}
export function parsePocketVision(raw,req){
  let d;
  try{d=JSON.parse(String(raw||'').trim().replace(/^\x60{3}(?:json)?\s*/i,'').replace(/\s*\x60{3}$/,'').trim());}
  catch{return stop('AI не повернув придатний до перевірки JSON. Не вгадуємо напрям.');}
  if(!d||typeof d!=='object'||d.readable!==true)return stop('На виділеному графіку недостатньо читабельних свічок та індикаторів.');
  const direction=['UP','DOWN','STOP'].includes(d.direction)?d.direction:'STOP';
  const reason=typeof d.reason==='string'?d.reason.trim().slice(0,550):'';
  const risk=typeof d.risk==='string'?d.risk.trim().slice(0,350):'';
  const sourcePair=typeof d.visible_pair==='string'?d.visible_pair.toUpperCase().replace(/[^A-Z0-9]/g,''):'';
  const chosenPair=req.pair.toUpperCase().replace(/[^A-Z0-9]/g,'');
  if(sourcePair&&sourcePair!=='UNKNOWN'&&sourcePair!==chosenPair)
    return stop('На фото може бути інша пара, ніж вибрана в налаштуваннях. Виправ пару.');
  if(reason.length<35||risk.length<20)return stop('Модель не надала достатньо конкретного пояснення та ризиків.');
  const observations=Array.isArray(d.observations)?
    d.observations.filter(x=>typeof x==='string'&&x.trim().length>=8).slice(0,5).map(x=>x.slice(0,170)):[];
  if(req.expiry_seconds<req.chart_timeframe_seconds)
    return stop('Експірація коротша за одну свічку. За цим кадром такого руху не перевірити.',risk);
  if(direction!=='STOP'&&observations.length<2)
    return stop('Модель не назвала дві незалежні конкретні ознаки на графіку.',risk);
  return {...stop(reason,risk),direction,reason,risk,observations,picture_only:true,
    timeframe_seconds:req.chart_timeframe_seconds,expiry_seconds:req.expiry_seconds};
}
const SYSTEM=String.raw`Ти JEV — обережний дослідник СКРІНШОТІВ Pocket Option.
Оцінюй лише видимі свічки, імпульс, підтримку/опір, moving average або RSI ТІЛЬКИ коли індикатор справді видно.
Немає live OTC-котирувань, виконання угод, точної ціни чи майбутніх даних. НЕ підмінюй котирування Pocket Option даними Bybit або Binance.
Користувач може обрізати зображення, тому якщо назви пари не видно, напиши visible_pair="unknown". Не вигадуй пару.
Дай дослідницьку гіпотезу UP, DOWN або STOP на обрану експірацію. UP/DOWN лише за ДВОМА різними, видимими та несуперечливими ознаками. Без достатніх підтверджень — STOP.
Не плутай уже намальований рух із майбутнім. Без вигаданих відсотків точності та гарантованих сигналів. Можна втратити всю ставку.
Відповідь лише JSON: {"readable":true,"direction":"UP","visible_pair":"unknown",
"observations":["перша конкретна ознака","друга конкретна ознака"],
"reason":"обережне пояснення гіпотези або STOP українською",
"risk":"чому прогноз може не справдитися"}. Не наказуй робити ставки.`;
export default async function handler(req,res){
  cors(req,res);
  if(req.method==='OPTIONS')return res.status(204).end();
  if(req.method!=='POST')return res.status(405).json({error:'POST only'});
  if(!ORIGINS.has(req.headers.origin))return res.status(403).json({error:'Недозволений сайт.'});
  if(!process.env.JEV_ACCESS_TOKEN||!validAccess(req))return res.status(401).json({error:'Невірний код доступу JEV.'});
  const p=provider();if(!p)return res.status(503).json({error:'На сервері немає робочого GEMINI_API_KEY або APINEX_API_KEY.'});
  const body=req.body;
  if(!body||typeof body!=='object'||Array.isArray(body))return res.status(400).json({error:'Недійсні параметри.'});
  const pair=String(body.pair||'').trim(),timeframe=Number(body.chart_timeframe_seconds),
    expiry=Number(body.expiry_seconds),payout=Number(body.payout_pct);
  if(!/^[A-Za-z0-9 /._-]{3,50}$/.test(pair)||!TF.has(timeframe)||!EXPIRIES.has(expiry)||
    !Number.isFinite(payout)||payout<=0||payout>100)
    return res.status(400).json({error:'Перевір пару, свічку, експірацію та виплату.'});
  const image=body.image;
  if(typeof image!=='string'||image.length<100||image.length>Math.ceil(MAX_BYTES*4/3)+8||
    !/^[A-Za-z0-9+/]+={0,2}$/.test(image))
    return res.status(413).json({error:'Зображення має бути JPG/PNG/WebP до 2 МБ після кадрування.'});
  const binary=Buffer.from(image,'base64'),mime=binary.length<=MAX_BYTES?imageType(binary):null;
  if(!mime)return res.status(415).json({error:'Невірний формат або завелике фото.'});
  if(expiry<timeframe)return res.status(200).json({...stop(
    'Експірація коротша за тривалість однієї свічки. Зміни таймфрейм або експірацію.'),
    provider:'rules',model:null,expiry_seconds:expiry,chart_timeframe_seconds:timeframe});
  const prompt='Користувач вибрав '+pair+', свічка '+timeframe+' секунд, експірація '+
    expiry+' секунд, виплата '+payout+'%. Є ЛИШЕ вирізаний скріншот графіка; '+
    'незалежних котирувань немає. Якщо назву пари не видно — visible_pair="unknown". '+
    'Не вигадуй поточну ціну, точність або RSI, якого немає в кадрі.';
  const gemini=p.name==='gemini';
  const url=gemini?'https://generativelanguage.googleapis.com/v1beta/models/'+encodeURIComponent(p.model)+':generateContent':
    'https://api.apinex.bond/v1/chat/completions';
  const headers=gemini?{'Content-Type':'application/json','x-goog-api-key':p.key}:
    {'Content-Type':'application/json',Authorization:'Bearer '+p.key};
  const payload=gemini?{
    systemInstruction:{parts:[{text:SYSTEM}]},
    contents:[{role:'user',parts:[{text:prompt},{inlineData:{mimeType:mime,data:image}}]}],
    generationConfig:{temperature:0,responseMimeType:'application/json',maxOutputTokens:750}
  }:{
    model:p.model,temperature:0,stream:false,max_tokens:750,
    messages:[{role:'system',content:SYSTEM},{role:'user',content:[
      {type:'text',text:prompt},{type:'image_url',image_url:{url:'data:'+mime+';base64,'+image}}]}]
  };
  try{
    const response=await fetch(url,{method:'POST',headers,body:JSON.stringify(payload),
      signal:AbortSignal.timeout(27000)});
    if(!response.ok)return res.status(response.status===402?402:response.status===429?429:502).json({
      error:response.status===402?'HTTP 402: AI-провайдер обмежив доступ. Фото НЕ проаналізовано.':
        response.status===429?'Вичерпано квоту AI-провайдера.':
        'AI відхилив запит (HTTP '+response.status+'). Фото НЕ проаналізовано.'});
    const data=await response.json();
    const content=data?.choices?.[0]?.message?.content;
    const raw=gemini?(data?.candidates?.[0]?.content?.parts||[]).map(x=>x.text||'').join(''):
      typeof content==='string'?content:Array.isArray(content)?content.map(x=>x.text||'').join(''):'';
    const parsed=parsePocketVision(raw,{pair,chart_timeframe_seconds:timeframe,expiry_seconds:expiry});
    return res.status(200).json({...parsed,provider:p.name,model:p.model,
      pair_selected:pair,payout_pct:payout,expiry_seconds:expiry,
      chart_timeframe_seconds:timeframe,received_at:new Date().toISOString()});
  }catch(e){
    return res.status(504).json({error:e?.name==='TimeoutError'?'Модель не відповіла за 27 секунд.':
      'Немає зв’язку з AI. Аналіз фото не відбувся.'});
  }
}
