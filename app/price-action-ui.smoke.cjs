/* jsdom smoke: the actual existing Myshka page, public market transport mocked. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'myshka-app.html'),'utf8');
const load=name=>fs.readFileSync(path.join(root,'app',name),'utf8');
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function rows(minutes,count){
  const step=minutes*60000,now=Date.now();
  const last=Math.floor((now-2*step-3000)/step)*step;
  const arr=[];
  for(let i=0;i<count;i++){
    const phase=i*.27;
    const close=100+Math.sin(phase)*1.8+i*.008;
    const open=100+Math.sin((i-1)*.27)*1.8+(i-1)*.008;
    arr.push([String(last-(count-1-i)*step),String(open),
      String(Math.max(close,open)+.4),String(Math.min(close,open)-.4),
      String(close),'20','0']);
  }
  return arr.reverse();
}
async function main(){
  const dom=new JSDOM(html,{url:'https://omeljanpadovcky-create.github.io/T/myshka-app.html',
    runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,d=w.document;
  const urls=[];
  w.fetch=async url=>{
    urls.push(String(url));
    const interval=new URL(url).searchParams.get('interval');
    return {ok:true,json:async()=>({retCode:0,result:{
      symbol:'BTCUSDT',category:'linear',list:rows(Number(interval),interval==='1'?430:140)
    }})};
  };
  w.eval(load('price-action-core.js'));
  w.eval(load('price-action-ui.js'));
  await sleep(1500);
  const text=d.getElementById('pa-output').textContent;
  assert.ok(text.includes('M1')&&text.includes('M5'),text.slice(0,400));
  assert.ok(text.includes('walk-forward'));
  assert.equal(urls.length,2,'requests only M1 and M5 OHLC; no private endpoint');
  assert.equal(urls.every(x=>x.includes('category=linear')),true);
  assert.ok(/WAIT|UP|DOWN/.test(text));
  assert.ok(!text.includes('Куплено')&&!text.includes('Ордер відкритий'));
  let calls=urls.length;
  d.getElementById('pa-run').click();
  await sleep(1500);
  assert.equal(urls.length,calls+2,'manual refresh asks for two closed feeds');
  w.fetch=async()=>({ok:false,status:503});
  d.getElementById('pa-run').click();
  await sleep(100);
  assert.ok(d.getElementById('pa-output').textContent.includes('Немає перевіреного'));
  assert.ok(!d.getElementById('pa-output').textContent.includes('правильних'));
  dom.window.close();
  console.log('Price Action UI: real DOM, closed-data transport, loading, refresh, fail-closed, no orders passed.');
}
main().catch(e=>{console.error(e);process.exitCode=1;});
