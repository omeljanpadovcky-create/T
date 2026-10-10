import { timingSafeEqual } from 'node:crypto';
const ALLOWED_ORIGINS = new Set(['https://omeljanpadovcky-create.github.io','http://127.0.0.1:18765','http://localhost:18765']);
const APINEX_ENDPOINT = "https://api.apinex.bond/v1/chat/completions";
const FREE_MODELS = [
  "free/gpt-5.6-luna",
  "free/deepseek-v4.1-flash",
  "free/gemini-3.8-flash"
];
const DATA_BASE = "https://omeljanpadovcky-create.github.io/T/crypto_myshka/data";

const SYSTEM = `Ти JEV — крипто-аналітик у системі Криптомишка.
Відповідай українською, коротко й по суті.
Не копіюй чужі сигнали як істину. Відділяй факт від припущення.
ITstatti — джерело контексту/методології, а не безумовний авторитет.
Не обіцяй прибуток і не давай безумовних команд "купуй/продавай".
Коли даних недостатньо — прямо скажи це.
Якщо користувач питає про актив, врахуй наданий контекст: ринок, останні пости ITstatti, JEV-новини та матеріали бази.
Можеш пояснювати ризик, сценарії, що перевірити, і на які рівні/події звернути увагу.`;

function compactItem(x){
  return {
    source:x.source,
    title:x.title,
    summary:(x.summary||"").slice(0,500),
    url:x.url,
    published_at:x.published_at,
    risk:x.risk,
    impact:x.impact,
    assets:x.assets,
    topics:x.topics,
    jev:(x.jev_ai&&x.jev_ai.short_conclusion)||x.jev_take||null
  };
}

async function getJson(url){
  const r=await fetch(url,{headers:{"User-Agent":"CryptoMyshka-JEV-Chat/1.0"}});
  if(!r.ok) throw new Error(`context ${r.status}`);
  return r.json();
}

function termsOf(message){
  return String(message||"")
    .toLowerCase()
    .replace(/[^a-zа-яіїєґ0-9$\-\s]/gi," ")
    .split(/\s+/)
    .filter(x=>x.length>=3)
    .slice(0,12);
}

function score(item, terms){
  const blob=((item.title||"")+" "+(item.summary||"")+" "+((item.assets||[]).join(" "))+" "+((item.topics||[]).join(" "))).toLowerCase();
  return terms.reduce((n,t)=>n+(blob.includes(t)?1:0),0);
}

async function contextFor(message){
  const [feed,news]=await Promise.all([
    getJson(`${DATA_BASE}/feed.json?ts=${Date.now()}`).catch(()=>({items:[],market:{}})),
    getJson(`${DATA_BASE}/news.json?ts=${Date.now()}`).catch(()=>({items:[]}))
  ]);
  const terms=termsOf(message);
  const live=(feed.items||[])
    .filter(x=>!x.knowledge)
    .map(x=>({x,s:score(x,terms)}))
    .sort((a,b)=>b.s-a.s)
    .slice(0,8)
    .map(o=>compactItem(o.x));
  const knowledge=(feed.items||[])
    .filter(x=>x.knowledge)
    .map(x=>({x,s:score(x,terms)}))
    .sort((a,b)=>b.s-a.s)
    .slice(0,6)
    .map(o=>compactItem(o.x));
  const events=(news.items||[])
    .map(x=>({x,s:score(x,terms)}))
    .sort((a,b)=>(b.s-a.s)||((b.x.impact||0)-(a.x.impact||0)))
    .slice(0,8)
    .map(o=>compactItem(o.x));
  return {
    generated_at:feed.generated_at,
    market:feed.market||{},
    live,
    knowledge,
    events
  };
}

function replyError(status, message) {
  const error = new Error(message);
  error.status = status;
  return error;
}

async function callGemini(apiKey, messages) {
  const model = process.env.JEV_CLOUD_MODEL || 'gemini-2.5-flash-lite';
  const systemText = messages.filter(x => x.role === 'system').map(x => x.content).join('\\n\\n');
  const conversation = messages.filter(x => x.role !== 'system')
    .map(x => ({role:x.role === 'assistant' ? 'model' : 'user',parts:[{text:x.content}]}));
  const response = await fetch('https://generativelanguage.googleapis.com/v1beta/models/' +
    encodeURIComponent(model) + ':generateContent', {
    method:'POST',
    headers:{'Content-Type':'application/json','x-goog-api-key':apiKey},
    body:JSON.stringify({
      systemInstruction:{parts:[{text:systemText}]},
      contents:conversation,
      generationConfig:{temperature:0.25,maxOutputTokens:850}
    }),
    signal:AbortSignal.timeout(28000)
  });
  if (!response.ok) {
    const status = response.status;
    throw replyError(status === 402 || status === 429 ? status : 502,
      status === 402 ? 'Gemini: HTTP 402 — перевір баланс/доступ до моделі.' :
      status === 429 ? 'Gemini: квота або обмеження частоти запитів.' :
      status === 401 || status === 403 ? 'Gemini: API-ключ не має доступу до моделі.' :
      status === 404 ? 'Gemini: модель не знайдено в цьому проєкті.' :
      'Gemini: помилка сервісу (HTTP ' + status + ').');
  }
  const data = await response.json();
  const text = data?.candidates?.[0]?.content?.parts?.map(p => p.text || '').join('').trim();
  if (!text) throw replyError(502,'Gemini не повернув текстової відповіді.');
  return {text,model,provider:'gemini'};
}

async function callModel(apiKey,messages){
  let last="";
  for(const model of FREE_MODELS){
    for(let attempt=0;attempt<2;attempt++){
      const r=await fetch(APINEX_ENDPOINT,{
        method:"POST",
        headers:{
          "Authorization":`Bearer ${apiKey}`,
          "Content-Type":"application/json",
          "Accept":"application/json"
        },
        body:JSON.stringify({
          model,
          messages,
          temperature:0.25,
          max_tokens:850
        })
      });
      if(r.ok){
        const j=await r.json();
        const text=j?.choices?.[0]?.message?.content?.trim();
        if(text && !text.includes("<tool_call>")) return {text,model,provider:'apinex'};
        last=`empty/malformed response from ${model}`;
        break;
      }
      // Do not expose provider raw error bodies or retry billing failures.
      last='APInex: помилка API (HTTP '+r.status+')';
      if(r.status===401) throw replyError(502,'APInex відхилив API-ключ.');
      if(r.status===402) throw replyError(402,'APInex: HTTP 402 — обмеження оплати, балансу або квоти. Спробуй прямий Gemini API.');
      if(r.status===429) throw replyError(429,'APInex: квота або обмеження частоти запитів.');
      if(r.status===400 || r.status===404 || r.status===422) break;
      if(r.status===429 || r.status===502 || r.status===503){
        await new Promise(ok=>setTimeout(ok,700*(attempt+1)));
        continue;
      }
      break;
    }
  }
  throw new Error(last||"JEV unavailable");
}

export default async function handler(req,res){
  const origin = req.headers.origin;
  if (ALLOWED_ORIGINS.has(origin)) res.setHeader('Access-Control-Allow-Origin',origin);
  res.setHeader('Vary','Origin');
  res.setHeader('Access-Control-Allow-Headers','Content-Type,X-JEV-Access');
  res.setHeader('Access-Control-Allow-Methods','POST,OPTIONS');
  res.setHeader('Cache-Control','no-store');
  if(req.method==='OPTIONS') return res.status(204).end();
  if(req.method!=='POST') return res.status(405).json({error:'POST only'});
  if(!ALLOWED_ORIGINS.has(origin)) return res.status(403).json({error:'Недозволене джерело запиту.'});

  const expected=process.env.JEV_ACCESS_TOKEN || '';
  const supplied=req.headers['x-jev-access'] || '';
  if(expected.length<24 || typeof supplied!=='string' || supplied.length!==expected.length ||
    !timingSafeEqual(Buffer.from(supplied),Buffer.from(expected)))
    return res.status(401).json({error:'Потрібен правильний код доступу JEV.'});

  const geminiKey=(process.env.GEMINI_API_KEY || '').trim();
  const apinexKey=(process.env.APINEX_API_KEY || '').trim();
  if(!geminiKey && !apinexKey) return res.status(503).json({error:'Немає налаштованого AI-провайдера на сервері.'});

  const message=String(req.body?.message||'').trim().slice(0,2000);
  const history=Array.isArray(req.body?.history)?req.body.history.slice(-6):[];
  if(!message) return res.status(400).json({error:'Напиши запитання.'});

  try{
    const ctx=await contextFor(message);
    const messages=[
      {role:'system',content:SYSTEM},
      {role:'system',content:'Контекст із публічних джерел КриптоМишки (може бути застарілим/неповним):\\n'+JSON.stringify(ctx).slice(0,14000)},
      ...history.map(x=>({role:x.role==='assistant'?'assistant':'user',content:String(x.content||'').slice(0,1000)})),
      {role:'user',content:message}
    ];
    const out=geminiKey ? await callGemini(geminiKey,messages) : await callModel(apinexKey,messages);
    return res.status(200).json({reply:out.text,model:out.model,provider:out.provider,
      context_generated_at:ctx.generated_at,source:'jev_ai',trading_enabled:false});
  }catch(e){
    const code=[402,429,504].includes(e?.status)?e.status:502;
    return res.status(code).json({error:String(e?.message || 'Не вдалося отримати відповідь JEV.').slice(0,260)});
  }
}
