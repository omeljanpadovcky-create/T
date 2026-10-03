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
        if(text && !text.includes("<tool_call>")) return {text,model};
        last=`empty/malformed response from ${model}`;
        break;
      }
      const body=(await r.text()).slice(0,300);
      last=`${r.status}: ${body}`;
      if(r.status===401) throw new Error("APINEX_KEY");
      if(r.status===402 || r.status===400 || r.status===404 || r.status===422) break;
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
  res.setHeader("Access-Control-Allow-Origin","*");
  res.setHeader("Access-Control-Allow-Headers","Content-Type");
  res.setHeader("Access-Control-Allow-Methods","POST,OPTIONS");
  if(req.method==="OPTIONS") return res.status(204).end();
  if(req.method!=="POST") return res.status(405).json({error:"POST only"});

  const key=process.env.APINEX_API_KEY;
  if(!key) return res.status(503).json({error:"JEV backend not configured"});

  const message=String(req.body?.message||"").trim().slice(0,2500);
  const history=Array.isArray(req.body?.history)?req.body.history.slice(-8):[];
  if(!message) return res.status(400).json({error:"Empty message"});

  try{
    const ctx=await contextFor(message);
    const messages=[
      {role:"system",content:SYSTEM},
      {role:"system",content:"Актуальний контекст Криптомишки:\n"+JSON.stringify(ctx).slice(0,22000)},
      ...history.map(x=>({role:x.role==="assistant"?"assistant":"user",content:String(x.content||"").slice(0,1800)})),
      {role:"user",content:message}
    ];
    const out=await callModel(key,messages);
    return res.status(200).json({
      reply:out.text,
      model:out.model,
      context_generated_at:ctx.generated_at
    });
  }catch(e){
    const msg=String(e?.message||e);
    const code=msg==="APINEX_KEY"?401:502;
    return res.status(code).json({error:msg});
  }
}
