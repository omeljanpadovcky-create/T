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
  const old={gemini:process.env.GEMINI_API_KEY,access:process.env.JEV_ACCESS_TOKEN};
  process.env.GEMINI_API_KEY='fake-private-gemini-key';
  process.env.JEV_ACCESS_TOKEN=access;
  return Promise.resolve().then(fn).finally(()=>{
    if(old.gemini===undefined) delete process.env.GEMINI_API_KEY; else process.env.GEMINI_API_KEY=old.gemini;
    if(old.access===undefined) delete process.env.JEV_ACCESS_TOKEN; else process.env.JEV_ACCESS_TOKEN=old.access;
  });
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
  const valid=parseVision(JSON.stringify({direction:'ВНИЗ',readable:true,
    chart_timeframe:'unknown',test_expiry_seconds:60,evidence:'Кілька нижчих максимумів на графіку.'}),'1m');
  assert.equal(valid.action,'SELL');
  assert.equal(valid.test_expiry_seconds,60);
  assert.equal(valid.signal_validated,false);
});
test('cloud health requires secrets, access code and allowed origin',async()=>{
  await withSecrets(async()=>{
    const ok=response();await health(request('GET'),ok);
    assert.equal(ok.code,200);assert.equal(ok.body.ready,true);
    assert.equal(ok.headers['Access-Control-Allow-Origin'],origin);
    const denied=response();await health(request('GET',null,{'x-jev-access':'bad'}),denied);
    assert.equal(denied.code,401);assert.equal(denied.body.ready,false);
    const cors=response();await health(request('GET',null,{origin:'https://attacker.example'}),cors);
    assert.equal(cors.code,403);
    assert.equal(cors.headers['Access-Control-Allow-Origin'],undefined);
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
      assert.match(url,/generativelanguage\.googleapis\.com/);
      assert.equal(opts.headers['x-goog-api-key'],'fake-private-gemini-key');
      const payload=JSON.parse(opts.body);
      assert.equal(payload.contents[0].parts[1].inlineData.data,fakePng);
      return {ok:true,json:async()=>({candidates:[{content:{parts:[{text:JSON.stringify({
        direction:'ВГОРУ',readable:true,chart_timeframe:'unknown',
        test_expiry_seconds:60,evidence:'Видно кілька вищих мінімумів на графіку.'
      })}]}}]})};
    };
    try {
      const res=response();await vision(request('POST',{image:fakePng,chart_timeframe:'1m'}),res);
      assert.equal(res.code,200);
      assert.equal(res.body.action,'BUY');
      assert.equal(res.body.test_expiry_seconds,60);
      assert.equal(res.body.source,'cloud_gemini');
      assert.equal(res.body.expiry_validated,false);
      assert.equal(res.body.model,'gemini-2.5-flash');
    }finally{globalThis.fetch=old;}
  });
});
