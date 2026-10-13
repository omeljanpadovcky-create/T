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
  const scannedSizes=[];
  w.cryptoMyshkaPhotoScan={
    findChartBounds:()=>({x:25,y:35,w:500,h:250}),
    analyzePixels:pixels=>{
      callCount++;
      scannedSizes.push([pixels.width,pixels.height]);
      const isFull=pixels.width>600;
      const weaker=mode==='fallback'&&isFull;
      const shortMove=mode==='conflict'?'lower':'higher';
      const count=(green,red)=>({count:green+red,green,red,
        greenPct:100*green/(green+red),redPct:100*red/(green+red)});
      return {recognized:true,reliable:!weaker,
        trendState:weaker?'unreliable':mode==='fallback'?'sideways':
          mode==='conflict'?'mixed':mode,
        visualDirection:mode==='up'?'up':'unknown',
        totalGreen:12,totalRed:8,totalSample:20,
        green:4,red:2,candidates:20,qualityScore:weaker?41:96,
        analytics:{
          total:count(12,8),recent12:count(8,4),
          previous6:count(1,5),recent6:count(5,1),
          greenDeltaPp:100*(5/6-1/6),recentLevel:shortMove,
          contrast:mode==='conflict',
          thirds:[{name:'Початок',...count(4,2)},
            {name:'Середина',...count(3,4)},
            {name:'Кінець',...count(5,2)}]
        },
        structure:{sample:12,recent:6,green:5,red:1,shortMove,
          highShape:'higher',lowShape:'higher',finalColor:'green',sameColor:3},
        observedDirection:mode==='up'?'Пізніші свічки вище':'Суперечливий рух'};
    }
  };
  w.HTMLCanvasElement.prototype.getContext=function(){
    const canvas=this;
    return {clearRect(){},drawImage(){},fillRect(){},strokeRect(){},setLineDash(){},
      getImageData(){return {width:canvas.width,height:canvas.height,
        data:new Uint8ClampedArray(canvas.width*canvas.height*4)};}};
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
  assert.ok(callCount>=1,'paste triggers immediate whole-frame scan');
  assert.ok(scannedSizes[0][0]>600&&scannedSizes[0][1]>500,
    'first scan must include the entire displayed screenshot');
  assert.match($('scan-scope').textContent,/всю площу скриншота/);
  assert.match($('result-title').textContent,/зростання/);
  assert.match($('minute-verdict').textContent,/наступної M1-свічки \(60 с\) невідомий/);
  assert.match($('result-facts').textContent,/M1 означає/);
  assert.match($('result-stats').textContent,/60%/);
  assert.match($('result-stats').textContent,/40%/);
  assert.match($('result-facts').textContent,/67%/);
  assert.match($('result-facts').textContent,/33%/);
  assert.match($('result-facts').textContent,/Верхні межі/);
  assert.match($('result-caution').textContent,/НЕ шанс BUY\/SELL/);
  assert.equal($('data-analytics').hidden,false);
  assert.equal($('analytics-grid').children.length,4);
  assert.match($('analytics-grid').textContent,/Увесь видимий графік/);
  assert.match($('analytics-grid').textContent,/Останні 12/);
  assert.match($('analytics-grid').textContent,/Попередні 6/);
  assert.match($('analytics-grid').textContent,/Останні 6/);
  assert.match($('analytics-comparison').textContent,/67 відсоткових пунктів/);
  assert.match($('analytics-phases').textContent,/початок/);
  assert.equal($('analytics-contrast').hidden,true);
  assert.ok([...$('analytics-grid').querySelectorAll('.analytics-green')].every(el=>
    el.style.width.endsWith('%')));
  assert.equal(networkCalls,0);
  mode='conflict';$('auto-select').click();
  assert.equal($('analytics-contrast').hidden,false);
  assert.match($('analytics-contrast').textContent,/переважно зелені/);
  assert.match($('analytics-contrast').textContent,/рівні нижчі/);
  assert.equal(networkCalls,0);
  // When platform labels/noise spoil full image recognition, detect the chart
  // only AFTER scanning the entire screenshot.
  mode='fallback';const prior=callCount;
  $('auto-select').click();
  assert.ok(callCount>=prior+2,'fall back to chart area after first full scan');
  assert.match($('result-title').textContent,/боковик/);
  assert.match($('scan-scope').textContent,/меню та підписи відокремлено/);
  assert.equal(networkCalls,0);
  // Manual crop is optional and the user can always reset to full image.
  const chart=$('chart-canvas');
  chart.getBoundingClientRect=()=>({left:0,top:0,width:chart.width,height:chart.height});
  chart.dispatchEvent(new w.MouseEvent('pointerdown',{bubbles:true,clientX:35,clientY:55}));
  chart.dispatchEvent(new w.MouseEvent('pointermove',{bubbles:true,clientX:465,clientY:290}));
  chart.dispatchEvent(new w.MouseEvent('pointerup',{bubbles:true,clientX:465,clientY:290}));
  assert.match($('scan-scope').textContent,/Обрано вручну/);
  $('auto-select').click();
  assert.match($('scan-scope').textContent,/меню та підписи відокремлено/);
  assert.equal(networkCalls,0);
  $('reset').click();
  assert.equal($('result').hidden,true);
  assert.equal($('canvas-area').hidden,true);
  console.log('Simple photo assistant: full image + candle analytics comparison, conflicting directions, zero trade/win predictions, manual selection, paste, no network OK');
  dom.window.close();
}
main().catch(error=>{console.error(error);process.exit(1);});
