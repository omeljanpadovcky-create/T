/* Smoke test for the simplified Crypto Myshka screenshot assistant. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
async function main(){
  const root=path.resolve(__dirname,'..');
  const html=fs.readFileSync(path.join(root,'myshka-app.html'),'utf8');
  const script=fs.readFileSync(path.join(root,'app/simple-photo-assistant.js'),'utf8');
  const dom=new JSDOM(html,{url:'https://omeljanpadovcky-create.github.io/T/myshka-app.html',
    runScripts:'outside-only',pretendToBeVisual:true});
  const w=dom.window,d=w.document;
  const $=id=>d.getElementById(id);
  assert.equal(d.querySelectorAll('input[type=file]').length,1);
  assert.ok(!$('ticket-buy')&&!$('ticket-sell')&&!$('cloud-access')&&!$('run-pocket-ai'));
  assert.ok(!html.includes('apinex')&&!html.includes('cryptoMyshkaBrowserVision'));
  let callCount=0;
  let mode='up';
  w.cryptoMyshkaPhotoScan={
    findChartBounds:()=>({x:25,y:35,w:500,h:250}),
    analyzePixels:()=>{
      callCount++;
      return {recognized:true,reliable:true,trendState:mode,
        visualDirection:mode==='up'?'up':mode==='down'?'down':'unknown',
        green:4,red:2,candidates:20,qualityScore:96,
        observedDirection:mode==='up'?'Пізніші свічки вище':'Суперечливий рух'};
    }
  };
  w.HTMLCanvasElement.prototype.getContext=function(){
    return {clearRect(){},drawImage(){},fillRect(){},strokeRect(){},setLineDash(){},
      getImageData(){return {width:this.width,height:this.height,
        data:new Uint8ClampedArray(this.width*this.height*4)};}};
  };
  w.Image=class{
    naturalWidth=960;naturalHeight=700;
    set src(v){this._src=v;queueMicrotask(()=>this.onload?.());}
    get src(){return this._src;}
  };
  let networkCalls=0;
  w.fetch=()=>{networkCalls++;throw Error('No network permitted');};
  w.eval(script);
  await new Promise(resolve=>setTimeout(resolve,20)); // DOMContentLoaded installs listeners
  const photo=new w.File([new Uint8Array([137,80,78,71,13,10,26,10,...Array(600).fill(25)])],
    'chart.png',{type:'image/png'});
  const paste=new w.Event('paste',{bubbles:true,cancelable:true});
  Object.defineProperty(paste,'clipboardData',{value:{items:[{
    type:'image/png',getAsFile:()=>photo
  }]}});
  d.dispatchEvent(paste);
  await new Promise(r=>setTimeout(r,45));
  assert.equal($('result').hidden,false);
  assert.equal($('canvas-area').hidden,false);
  assert.ok(callCount>=1,'upload must trigger immediate scan');
  assert.match($('result-title').textContent,/зростання/);
  assert.match($('minute-verdict').textContent,/наступної M1-свічки \(60 с\) невідомий/);
  assert.match($('result-facts').textContent,/M1 означає/);
  assert.match($('result-stats').textContent,/67%/);
  assert.match($('result-stats').textContent,/33%/);
  assert.match($('result-caution').textContent,/НЕ ймовірність BUY\/SELL/);
  assert.equal(networkCalls,0);
  mode='sideways';$('auto-select').click();
  assert.ok(callCount>=2);
  assert.match($('result-title').textContent,/боком/);
  assert.equal(networkCalls,0);
  $('reset').click();
  assert.equal($('result').hidden,true);
  assert.equal($('canvas-area').hidden,true);
  console.log('Simple photo assistant: automatic scan, percentage math, sideways, reset, NO network calls OK');
  dom.window.close();
}
main().catch(error=>{console.error(error);process.exit(1);});
