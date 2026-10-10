import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import vision, {parseVision} from '../api/chart-analysis.js';
import health from '../api/chart-health.js';

const origin='https://omeljanpadovcky-create.github.io';
const access='abcdefghijklmnopqrstuvwxyz123456';
const fakePng=Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),Buffer.from('test-image-bytes')]).toString('base64');
function response() {
  return {code:200, headers:{}, body:null,
    setHeader(k,v){this.headers[k]=v;},
    status(code){this.code=code;return this;},
    json(body){this.body=body;return this;},
    end(){return this;}};
}
function request(method, body, headers={}) {
  return {method,body,headers:{origin,'x-jev-access':access,...headers}};
}
function withSecrets(fn) {
  const old={gemini:process.env.GEMINI_API_KEY,apinex:process.env.APINEX_API_KEY,access:process.env.JEV_ACCESS_TOKEN};
  delete process.env.APINEX_API_KEY;
  process.env.GEMINI_API_KEY='fake-private-gemini-key';
  process.env.JEV_ACCESS_TOKEN=access;
  return Promise.resolve().then(fn).finally(()=>{
    if(old.gemini===undefined) delete process.env.GEMINI_API_KEY; else process.env.GEMINI_API_KEY=old.gemini;
    if(old.apinex===undefined) delete process.env.APINEX_API_KEY; else process.env.APINEX_API_KEY=old.apinex;
    if(old.access===undefined) delete process.env.JEV_ACCESS_TOKEN; else process.env.JEV_ACCESS_TOKEN=old.access;
  });
}
function confirmedBybit(url) {
  const link=new URL(url);
  const interval=Number(link.searchParams.get('interval'));
  const step=interval*60_000;
  const lastStart=Math.floor((Date.now()-3000)/step)*step-step;
  const rows=Array.from({length:80},(_,index)=>{
    const start=lastStart-index*step;
    const price=10000+(79-index)*2;
    return [start.toString(),(price-0.4).toString(),(price+1).toString(),
      (price-1).toString(),price.toString(),'100'];
  });
  return {ok:true,status:200,json:async()=>({retCode:0,result:{symbol:'BTCUSDT',list:rows}})};
}
function mockMarket(url) {
  if(String(url).startsWith('https://api.bybit.com/v5/market/kline')) return confirmedBybit(url);
  if(String(url).includes('/crypto_myshka/data/market_learning_5m.json'))
    return {ok:false,status:404};
  return null;
}
test('GitHub root and jev_api cloud endpoints stay identical',()=>{
  const here=path.dirname(fileURLToPath(import.meta.url));
  for(const file of ['chart-health.js','chart-analysis.js']){
    assert.equal(fs.readFileSync(path.resolve(here,'../api',file),'utf8'),
      fs.readFileSync(path.resolve(here,'../../api',file),'utf8'));
  }
});
test('strict parser rejects ungrounded claims, unknown timeframe, invalid expiry',()=>{
  assert.equal(parseVision('BUY BUY BUY').action,'SKIP');
  assert.equal(parseVision(JSON.stringify({direction:'ВГОРУ',readable:false,
    chart_timeframe:'1m',test_expiry_seconds:60,evidence:'Свічки вгору'})).action,'SKIP');
  assert.equal(parseVision(JSON.stringify({direction:'ВНИЗ',readable:true,
    chart_timeframe:'unknown',test_expiry_seconds:60,evidence:'Кілька нижчих максимумів на графіку.'})).action,'SKIP');
  assert.equal(parseVision(JSON.stringify({direction:'ВНИЗ',readable:true,
    chart_timeframe:'5m',test_expiry_seconds:30,evidence:'Кілька нижчих максимумів на графіку.'})).action,'SKIP');
  const modelOutput=JSON.stringify({direction:'ВНИЗ',readable:true,chart_timeframe:'unknown',
    horizon_minutes:5,evidence:'Кілька нижчих максимумів і спадний імпульс на графіку.',
    risk:'Відскок від підтримки може зламати спадний сценарій.'});
  assert.equal(parseVision(modelOutput,'1m').action,'SKIP','no market verification means STOP');
  const valid=parseVision(modelOutput,'1m',{intervals:[
    {regime:'down'},{regime:'down'},{regime:'range'}]});
  assert.equal(valid.action,'SELL');
  assert.equal(valid.horizon_minutes,5);
  assert.equal(valid.test_expiry_seconds,null);
  assert.equal(valid.signal_validated,false);
  assert.equal(parseVision(modelOutput,'15m',{intervals:[
    {regime:'down'},{regime:'down'},{regime:'range'}]}).action,'SKIP',
    'five minute hypothesis is invalid for fifteen minute candles');
});
test('cloud health requires secrets, access code, allowed origin and reachable Gemini model',async()=>{
  await withSecrets(async()=>{
    const old=globalThis.fetch;
    let calls=0;
    globalThis.fetch=async (url,opts)=>{
      calls++;
      assert.match(url,/generativelanguage\.googleapis\.com\/v1beta\/models\/gemini-2.5-flash/);
      assert.equal(opts.headers['x-goog-api-key'],'fake-private-gemini-key');
      return {ok:true,status:200};
    };
    try {
      const ok=response();await health(request('GET'),ok);
      assert.equal(ok.code,200);assert.equal(ok.body.ready,true);
      assert.equal(ok.headers['Access-Control-Allow-Origin'],origin);
      assert.equal(calls,1);
      const denied=response();await health(request('GET',null,{'x-jev-access':'bad'}),denied);
      assert.equal(denied.code,401);assert.equal(denied.body.ready,false);
      const cors=response();await health(request('GET',null,{origin:'https://attacker.example'}),cors);
      assert.equal(cors.code,403);
      assert.equal(cors.headers['Access-Control-Allow-Origin'],undefined);
      assert.equal(calls,1,'no provider request for unauthenticated calls');
      globalThis.fetch=async()=>({ok:false,status:429});
      const limited=response();await health(request('GET'),limited);
      assert.equal(limited.code,503);
      assert.equal(limited.body.ready,false);
    } finally {globalThis.fetch=old;}
  });
});
test('cloud screenshot requires authorization, valid image and valid timeframe',async()=>{
  await withSecrets(async()=>{
    const badAuth=response();await vision(request('POST',{image:fakePng},{'x-jev-access':'wrong'}),badAuth);
    assert.equal(badAuth.code,401);
    const badTf=response();await vision(request('POST',{image:fakePng,chart_timeframe:'1d'}),badTf);
    assert.equal(badTf.code,400);
    const badImage=response();await vision(request('POST',{image:'YWJjZA==',chart_timeframe:'1m'}),badImage);
    assert.notEqual(badImage.code,200);
    const cors=response();await vision(request('POST',{image:fakePng},{origin:'https://attacker.example'}),cors);
    assert.equal(cors.code,403);
  });
});
test('cloud screenshot calls Gemini server-side and returns bounded demo result',async()=>{
  await withSecrets(async()=>{
    const old=globalThis.fetch;
    globalThis.fetch=async (url,opts)=>{
      const market=mockMarket(url);
      if(market)return market;
      assert.match(url,/generativelanguage\.googleapis\.com/);
      assert.equal(opts.headers['x-goog-api-key'],'fake-private-gemini-key');
      const payload=JSON.parse(opts.body);
      assert.equal(payload.contents[0].parts[1].inlineData.data,fakePng);
      return {ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify({
        direction:'ВГОРУ',readable:true,chart_timeframe:'unknown',horizon_minutes:5,
        evidence:'Видно кілька вищих мінімумів, а EMA та імпульс підтверджують напрям.',
        risk:'Можливий хибний пробій через низький обсяг або швидкий розворот.'
      })}]}}]})};
    };
    try {
      const res=response();await vision(request('POST',{image:fakePng,chart_timeframe:'1m',
        market_symbol:'BTCUSDT',market_category:'linear'}),res);
      assert.equal(res.code,200);
      assert.equal(res.body.action,'BUY');
      assert.equal(res.body.horizon_minutes,5);
      assert.equal(res.body.test_expiry_seconds,null);
      assert.equal(res.body.source,'cloud_gemini');
      assert.equal(res.body.market_verified,true);
      assert.equal(res.body.expiry_validated,false);
      assert.equal(res.body.model,'gemini-2.5-flash-lite');
    }finally{globalThis.fetch=old;}
  });
});

test('APInex health uses GitHub-compatible env key only inside the server and never exposes it',async()=>{
  await withSecrets(async()=>{
    process.env.APINEX_API_KEY='fake-apinex-secret-keep-private';
    delete process.env.GEMINI_API_KEY; // direct Gemini takes precedence when configured
    const old=globalThis.fetch;
    globalThis.fetch=async (url,opts)=>{
      assert.equal(url,'https://api.apinex.bond/v1/models');
      assert.equal(opts.headers.Authorization,'Bearer fake-apinex-secret-keep-private');
      return {ok:true,status:200};
    };
    try {
      const ok=response();await health(request('GET'),ok);
      assert.equal(ok.code,200);
      assert.equal(ok.body.provider,'apinex');
      assert.equal(ok.body.model,'gemini-3.8-flash');
      assert.ok(!JSON.stringify(ok.body).includes(process.env.APINEX_API_KEY));
      const bad=response();await health(request('GET',null,{'x-jev-access':'not-valid'}),bad);
      assert.equal(bad.code,401);
      globalThis.fetch=async()=>({ok:false,status:403});
      const catalogBlocked=response();await health(request('GET'),catalogBlocked);
      assert.equal(catalogBlocked.code,200);
      assert.equal(catalogBlocked.body.provider,'apinex');
      assert.equal(catalogBlocked.body.ready,true);
      assert.equal(catalogBlocked.body.verified,false);
      assert.equal(catalogBlocked.body.probe,'model_catalog_denied');
    }finally{globalThis.fetch=old;}
  });
});

test('APInex vision uses authenticated OpenAI-compatible image_url format',async()=>{
  await withSecrets(async()=>{
    process.env.APINEX_API_KEY='fake-apinex-secret-keep-private';
    delete process.env.GEMINI_API_KEY; // direct Gemini takes precedence when configured
    const old=globalThis.fetch;
    globalThis.fetch=async (url,opts)=>{
      const market=mockMarket(url);
      if(market)return market;
      assert.equal(url,'https://api.apinex.bond/v1/chat/completions');
      assert.equal(opts.headers.Authorization,'Bearer fake-apinex-secret-keep-private');
      const payload=JSON.parse(opts.body);
      assert.equal(payload.model,'gemini-3.8-flash');
      assert.match(payload.messages[1].content[1].image_url.url,/^data:image\/png;base64,/);
      assert.ok(payload.messages[1].content[1].image_url.url.endsWith(fakePng));
      return {ok:true,status:200,json:async()=>({choices:[{message:{content:JSON.stringify({
        direction:'ВГОРУ',readable:true,chart_timeframe:'1m',horizon_minutes:5,
        evidence:'Є вищі мінімуми та висхідний імпульс на кількох таймфреймах.',
        risk:'Можливий розворот після імпульсу через низький обсяг торгів.'
      })}}]})};
    };
    try {
      const res=response();await vision(request('POST',{image:fakePng,chart_timeframe:'1m',
        market_symbol:'BTCUSDT',market_category:'linear'}),res);
      assert.equal(res.code,200);
      assert.equal(res.body.provider,'apinex');
      assert.equal(res.body.source,'cloud_apinex');
      assert.equal(res.body.signal_validated,false);
      assert.equal(res.body.expiry_validated,false);
      assert.ok(!JSON.stringify(res.body).includes(process.env.APINEX_API_KEY));
    }finally{globalThis.fetch=old;}
  });
});
