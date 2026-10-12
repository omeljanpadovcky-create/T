import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import pocketVision, {parsePocketVision} from '../api/pocket-vision.js';
const request={pair:'EUR/USD OTC',chart_timeframe_seconds:60,expiry_seconds:60};
const valid={readable:true,direction:'UP',visible_pair:'unknown',
  observations:['Є щонайменше кілька послідовних зелених свічок, видимих на фото.',
    'Нахил ковзної середньої на зображенні змінився вгору.'],
  reason:'На фото видно дві узгоджені ознаки короткострокового відскоку, проте напрям наступної свічки невідомий.',
  risk:'OTC ціна може розвернутися до експірації, можна втратити всю ставку.'};
test('No screenshot model schema means STOP',()=>{
  assert.equal(parsePocketVision('',request).direction,'STOP');
  assert.equal(parsePocketVision('{"readable":false}',request).direction,'STOP');
  assert.equal(parsePocketVision('{}',request).direction,'STOP');
});
test('Two visible observations permit labelled unverified hypothesis',()=>{
  const value=parsePocketVision(JSON.stringify(valid),request);
  assert.equal(value.direction,'UP');
  assert.equal(value.mode,'screenshot_hypothesis');
  assert.equal(value.quotes_verified,false);
  assert.equal(value.signal_validated,false);
  assert.equal(value.probability,null);
  assert.equal(value.orders_enabled,false);
  assert.equal(value.broker_verified,false);
});
test('Misidentified pair or weak evidence forces STOP',()=>{
  assert.equal(parsePocketVision(JSON.stringify({...valid,visible_pair:'GBP/USD OTC'}),request).direction,'STOP');
  assert.equal(parsePocketVision(JSON.stringify({...valid,observations:[]}),request).direction,'STOP');
  assert.equal(parsePocketVision(JSON.stringify({...valid,risk:'Too short'}),request).direction,'STOP');
});
test('Expiry below candle timeframe never becomes a direction',()=>{
  assert.equal(parsePocketVision(JSON.stringify(valid),{...request,expiry_seconds:30}).direction,'STOP');
});
test('Pocket endpoints are mirrored and do not fetch external quote feeds',()=>{
  const main=readFileSync(new URL('../../api/pocket-vision.js',import.meta.url),'utf8');
  const mirror=readFileSync(new URL('../api/pocket-vision.js',import.meta.url),'utf8');
  assert.equal(main,mirror);
  assert.doesNotMatch(main,/api\.bybit\.com|api\.binance\.com|pocketoption\.com\/api/);
});


// This tests the actual Vercel handler error surface, not a mocked happy-only UI.
test('Upstream APInex errors are actionable and do not expose credentials',async()=>{
  const oldEnv={a:process.env.APINEX_API_KEY,g:process.env.GEMINI_API_KEY,
    token:process.env.JEV_ACCESS_TOKEN,m:process.env.JEV_APINEX_MODEL};
  const oldFetch=globalThis.fetch,oldWarn=console.warn;
  const access='a'.repeat(32),secret='fake-token-never-log';
  process.env.APINEX_API_KEY=secret;
  delete process.env.GEMINI_API_KEY;
  process.env.JEV_ACCESS_TOKEN=access;
  process.env.JEV_APINEX_MODEL='gemini-3.8-flash';
  const png=Buffer.concat([Buffer.from([255,216,255]),Buffer.alloc(180,42)]).toString('base64');
  const body={pair:'EUR/USD OTC',chart_timeframe_seconds:60,expiry_seconds:60,payout_pct:92,image:png};
  const req={method:'POST',headers:{origin:'https://omeljanpadovcky-create.github.io',
    'x-jev-access':access},body};
  const response=()=>({code:200,body:null,headers:{},
    setHeader(k,v){this.headers[k]=v;},
    status(code){this.code=code;return this;},
    json(value){this.body=value;return this;},
    end(){return this;}});
  const warnings=[];
  console.warn=(...values)=>warnings.push(values.join(' '));
  async function run(override){
    globalThis.fetch=async (url,opts)=>{
      assert.equal(url,'https://api.apinex.bond/v1/chat/completions');
      const payload=JSON.parse(opts.body);
      assert.equal(payload.model,'gemini-3.8-flash');
      assert.ok(payload.max_tokens>=1200,'allow enough tokens for vision response');
      assert.ok(payload.messages[1].content[1].image_url.url.startsWith('data:image/jpeg;base64,'));
      return override;
    };
    const res=response();
    await pocketVision(req,res);
    assert.ok(!JSON.stringify(res.body).includes(secret),'never echo provider key');
    return res;
  }
  try{
    let out=await run({ok:false,status:402});
    assert.equal(out.code,402);assert.equal(out.body.code,'PROVIDER_CREDITS');
    out=await run({ok:false,status:404});
    assert.equal(out.code,502);assert.equal(out.body.code,'MODEL_NOT_FOUND');
    out=await run({ok:false,status:429});
    assert.equal(out.code,429);assert.equal(out.body.code,'PROVIDER_RATE_LIMIT');
    out=await run({ok:true,status:200,json:async()=>({choices:[{finish_reason:'length',
      message:{content:null}}]})});
    assert.equal(out.code,502);assert.equal(out.body.code,'MODEL_OUTPUT_TRUNCATED');
    out=await run({ok:true,status:200,json:async()=>({choices:[{message:{content:'hello'}}]})});
    assert.equal(out.code,502);assert.equal(out.body.code,'MODEL_INVALID_JSON');
    out=await run({ok:true,status:200,json:async()=>({choices:[{message:{content:JSON.stringify(valid)}}]})});
    assert.equal(out.code,200);assert.equal(out.body.direction,'UP');
    assert.equal(out.body.signal_validated,false);
    assert.equal(out.body.orders_enabled,false);
    assert.ok(warnings.every(value=>!value.includes(secret)));
  }finally{
    globalThis.fetch=oldFetch;console.warn=oldWarn;
    for(const [key,value] of Object.entries({
      APINEX_API_KEY:oldEnv.a,GEMINI_API_KEY:oldEnv.g,
      JEV_ACCESS_TOKEN:oldEnv.token,JEV_APINEX_MODEL:oldEnv.m
    })){
      if(value===undefined)delete process.env[key];
      else process.env[key]=value;
    }
  }
});
