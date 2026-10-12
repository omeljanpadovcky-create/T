/* Browser smoke for Pocket Lab. Run after npm install --no-save jsdom@26.1.0 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
async function main(){
  const root=path.resolve(__dirname,'..');
  const html=fs.readFileSync(path.join(root,'myshka-app.html'),'utf8');
  const script=fs.readFileSync(path.join(root,'app/pocket-option.js'),'utf8');
  const ticketScript=fs.readFileSync(path.join(root,'app/pocket-trade-ticket.js'),'utf8');
  const browserScript=fs.readFileSync(path.join(root,'app/browser-vision.js'),'utf8');
  const dom=new JSDOM(html,{url:'https://omeljanpadovcky-create.github.io/T/myshka-app.html#analysis',
    pretendToBeVisual:true,runScripts:'outside-only'});
  const w=dom.window,d=w.document;
  w.scrollTo=()=>{};
  w.confirm=()=>true;
  let scanCalls=0;
  w.cryptoMyshkaPhotoScan={
    findChartBounds:()=>({x:20,y:15,w:330,h:185}),
    analyzePixels:()=>{scanCalls++;return {recognized:true,visualDirection:'down',candidates:25,
      reliable:true,partial:false,qualityScore:83,green:2,red:5,
      observedDirection:'Пізніші свічки нижче'};}
  };
  let usedCrop=false;
  w.HTMLCanvasElement.prototype.getContext=function(){
    return {clearRect(){},drawImage(){},fillRect(){},strokeRect(){},setLineDash(){},
      getImageData(){return {width:this.width,height:this.height,
        data:new Uint8ClampedArray(this.width*this.height*4)};}};
  };
  w.HTMLCanvasElement.prototype.toDataURL=function(){
    usedCrop=true;
    return 'data:image/jpeg;base64,'+Buffer.from([255,216,255,...new Array(300).fill(7)]).toString('base64');
  };
  w.Image=class{
    naturalWidth=640;naturalHeight=360;
    set src(value){this._src=value;queueMicrotask(()=>this.onload?.());}
    get src(){return this._src;}
  };
  const requests=[];
  let visionProblem=null;
  w.fetch=async (url,opts={})=>{
    requests.push({url:String(url),opts});
    if(String(url).endsWith('/api/chart-health'))
      return {ok:true,status:200,json:async()=>({ready:true,provider:'gemini',
        model:'gemini-2.5-flash-lite',verified:false})};
    if(String(url).endsWith('/api/pocket-vision')){
      if(visionProblem)return {ok:false,status:visionProblem.status,
        json:async()=>({error:visionProblem.error,code:visionProblem.code})};
      if(!opts.method)return {ok:false,status:405,json:async()=>({error:'POST only'})};
      const body=JSON.parse(opts.body);
      assert.equal(body.pair,'EUR/USD OTC');
      assert.equal(body.chart_timeframe_seconds,60);
      assert.equal(body.expiry_seconds,60);
      assert.equal(body.payout_pct,92);
      assert.equal(body.image.startsWith('/9j/'),true);
      return {ok:true,status:200,json:async()=>({
        mode:'screenshot_hypothesis',direction:'UP',orders_enabled:false,quotes_verified:false,broker_verified:false,signal_validated:false,observations:['На фото є свічки із вищими мінімумами','Другий незалежний видимий сигнал підтверджує рух'],reason:'Два індикатори узгоджені, але це лише гіпотеза з фото.',
        risk:'Несподіваний розворот може призвести до втрати всієї ставки.',
        provider:'gemini',model:'test'
      })};
    }
    throw Error('Unexpected URL: '+url);
  };
  w.eval(browserScript);
  w.eval(script);
  w.eval(ticketScript);
  await new Promise(r=>setTimeout(r,20));
  assert.equal(d.querySelectorAll('.mobile-nav button').length,5);
  assert.equal(d.querySelector('#pocket-pair').value,'EUR/USD OTC');
  assert.equal(d.querySelector('#pocket-expiry').value,'60');
  assert.equal(d.querySelector('#pocket-timeframe').value,'60');
  assert.match(d.querySelector('#pocket-math').textContent,/52,08/);
  assert.doesNotMatch(d.querySelector('#screen-analysis').textContent,/Bybit V5|Master Traders|TSLAUSDT/);
  assert.equal(d.querySelector('#screen-analysis').hidden,false);
  const press=sel=>{const el=d.querySelector(sel);assert.ok(el,sel);el.click();return el;};
  assert.match(d.querySelector('#ticket-guide-action').textContent,/Додати фото/);
  let filePickerCalls=0;
  const photoInput=d.querySelector('#pocket-photo'),originalPhotoClick=photoInput.click.bind(photoInput);
  photoInput.click=()=>{filePickerCalls++;};
  press('#ticket-guide-action');
  assert.equal(filePickerCalls,1,'the demo ticket opens screenshot picker');
  photoInput.click=originalPhotoClick;
  press('.mobile-nav [data-go="history"]');
  assert.equal(d.querySelector('#screen-history').hidden,false);
  press('.mobile-nav [data-go="analysis"]');
  d.querySelector('#cloud-endpoint').value='https://t-zeta-ashy.vercel.app';
  d.querySelector('#cloud-access').value='a'.repeat(32);
  press('#cloud-connect');
  await new Promise(r=>setTimeout(r,20));
  assert.match(d.querySelector('#cloud-status').textContent,/Каталог .* відповідає/);
  assert.equal(w.cryptoMyshkaPocket.getAnalysisState().cloudReady,true);
  assert.equal(w.cryptoMyshkaPocket.getAnalysisState().hasImage,false);
  assert.match(d.querySelector('#ai-status').textContent,/Додай свіжий скриншот/);
  assert.match(d.querySelector('#ticket-guide-note').textContent,/API доступний/);
  const png=w.document.createElement('input');
  const fake=new w.File([new Uint8Array([137,80,78,71,13,10,26,10,...new Array(300).fill(1)])],
    'pocket.png',{type:'image/png'});
  // Trigger the same handler as Ctrl+V: jsdom provides FileReader and ClipboardEvent data.
  const event=new w.Event('paste',{bubbles:true,cancelable:true});
  Object.defineProperty(event,'clipboardData',{value:{items:[{type:'image/png',getAsFile:()=>fake}]}});
  const requestsBeforeUpload=requests.length;
  d.dispatchEvent(event);
  await new Promise(r=>setTimeout(r,75));
  assert.equal(d.querySelector('#photo-stage').hidden,false);
  assert.ok(scanCalls>=1,'screenshot upload must immediately scan past candles');
  assert.match(d.querySelector('#scan-output').textContent,/JEV LITE/);
  assert.equal(w.cryptoMyshkaPocket.getAnalysisState().localReport.kind,'historical_only');
  assert.equal(w.cryptoMyshkaPocket.getAnalysisState().localReport.direction,'down');
  assert.equal(requests.length,requestsBeforeUpload,'automatic scan must not call paid provider');
  const beforeRecrop=scanCalls;
  press('#reset-crop');
  assert.ok(scanCalls>beforeRecrop,'changing crop should automatically re-scan');
  assert.equal(d.querySelector('#run-pocket-ai').disabled,false);
  assert.match(d.querySelector('#ticket-guide-action').textContent,/Аналізувати фото JEV/);
  press('#scan-pixels');
  assert.match(d.querySelector('#scan-output').textContent,/МИНУЛІ СВІЧКИ/);
  assert.match(d.querySelector('#scan-output').textContent,/Падіння вже на фото/);
  assert.match(d.querySelector('#ai-direction').textContent,/ЛОКАЛЬНО/);
  assert.match(d.querySelector('#ai-reason').textContent,/розпізнано/i);
  assert.equal(w.cryptoMyshkaPocket.getScreenshotHypothesis(),null);
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),false);
  assert.equal(d.querySelector('#ticket-sell').classList.contains('jev-flash'),false);
  press('#ticket-guide-action');
  await new Promise(r=>setTimeout(r,30));
  assert.equal(usedCrop,true);
  assert.match(d.querySelector('#ai-direction').textContent,/BUY/);
  // Fresh cloud image-based hypothesis highlights only the matching manual DEMO direction.
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),true);
  assert.equal(d.querySelector('#ticket-sell').classList.contains('jev-flash'),false);
  assert.match(d.querySelector('#ticket-jev-hint').textContent,/лише для демо/);
  const originalGetter=w.cryptoMyshkaPocket.getScreenshotHypothesis;
  const fresh=originalGetter();
  assert.equal(fresh.source,'pocket_cloud_screenshot');
  assert.equal(fresh.signal_validated,false);
  w.cryptoMyshkaPocket.getScreenshotHypothesis=()=>({...fresh,direction:'DOWN'});
  w.dispatchEvent(new w.Event('crypto-myshka-jev-verdict-change'));
  assert.equal(d.querySelector('#ticket-sell').classList.contains('jev-flash'),true);
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),false);
  w.cryptoMyshkaPocket.getScreenshotHypothesis=()=>({...fresh,direction:'STOP'});
  w.dispatchEvent(new w.Event('crypto-myshka-jev-verdict-change'));
  assert.equal(d.querySelector('#ticket-sell').classList.contains('jev-flash'),false);
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),false);
  w.cryptoMyshkaPocket.getScreenshotHypothesis=()=>({...fresh,created:new Date(Date.now()-120000).toISOString()});
  w.dispatchEvent(new w.Event('crypto-myshka-jev-verdict-change'));
  assert.match(d.querySelector('#ticket-jev-direction').textContent,/застаріла/);
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),false);
  w.cryptoMyshkaPocket.getScreenshotHypothesis=originalGetter;
  w.dispatchEvent(new w.Event('crypto-myshka-jev-verdict-change'));
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),true);
  press('#save-paper');
  assert.equal(JSON.parse(w.localStorage.getItem('crypto-myshka-pocket-paper-v1')).length,1);
  press('.mobile-nav [data-go="history"]');
  assert.match(d.querySelector('#journal-list').textContent,/EUR\/USD OTC/);
  assert.match(d.querySelector('#journal-list').textContent,/Очікує|очікує/);
  // BUY/SELL buttons write isolated manual paper trades; never broker calls.
  press('.mobile-nav [data-go="analysis"]');
  assert.equal(d.querySelector('#ticket-expiry').value,'60');
  assert.equal(d.querySelector('#ticket-buy').disabled,false);
  press('#ticket-buy');
  let records=JSON.parse(w.localStorage.getItem('crypto-myshka-pocket-paper-v1'));
  assert.equal(records.length,2);
  assert.equal(records[0].source,'pocket_manual_demo');
  assert.equal(records[0].direction,'UP');
  assert.equal(records[0].broker_verified,false);
  assert.equal(d.querySelector('#ticket-sell').disabled,true);
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),false,
    'active demo trade must cancel animated encouragement');
  press('.mobile-nav [data-go="history"]');
  assert.match(d.querySelector('#journal-list').textContent,/РУЧНА DEMO/);
  assert.match(d.querySelector('#history-summary').textContent,/JEV: гіпотези/);
  assert.match(d.querySelector('#history-summary').textContent,/Ручні BUY \/ SELL/);
  records[0].expiresAt=new Date(Date.now()-5000).toISOString();
  w.localStorage.setItem('crypto-myshka-pocket-paper-v1',JSON.stringify(records));
  press('.mobile-nav [data-go="analysis"]');
  d.querySelector('#ticket-expiry').value='30';
  d.querySelector('#ticket-expiry').dispatchEvent(new w.Event('change',{bubbles:true}));
  assert.equal(d.querySelector('#pocket-expiry').value,'30');
  d.querySelector('#ticket-stake').value='7';
  d.querySelector('#ticket-stake').dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.equal(d.querySelector('#pocket-stake').value,'7');
  press('.mobile-nav [data-go="history"]');
  const manualCard=Array.from(d.querySelectorAll('.journal-card'))
    .find(x=>x.textContent.includes('РУЧНА DEMO'));
  assert.ok(manualCard,'manual trade present after expiry');
  const winButton=Array.from(manualCard.querySelectorAll('button'))
    .find(x=>x.textContent.includes('WIN'));
  assert.ok(winButton&&!winButton.disabled,'manual outcome can settle after expiry');
  winButton.click();
  records=JSON.parse(w.localStorage.getItem('crypto-myshka-pocket-paper-v1'));
  assert.equal(records[0].outcome,'hit');
  visionProblem={status:402,code:'PROVIDER_CREDITS',
    error:'APInex вимагає доступний баланс або квоту (HTTP 402).'};
  press('.mobile-nav [data-go="analysis"]');
  press('#run-pocket-ai');
  await new Promise(resolve=>setTimeout(resolve,30));
  assert.match(d.querySelector('#ai-status').textContent,/PROVIDER_CREDITS/);
  assert.match(d.querySelector('#ai-status').textContent,/HTTP 402/);
  assert.match(d.querySelector('#ai-reason').textContent,/Пізніші свічки нижче/);
  assert.match(d.querySelector('#ai-direction').textContent,/ЛОКАЛЬНО/);
  assert.match(d.querySelector('#ticket-jev-direction').textContent,/Локальний розбір/);
  assert.match(d.querySelector('#ticket-guide-action').textContent,/Сканувати локально/);
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),false);
  assert.match(d.querySelector('#scan-output').textContent,/JEV LITE/);
  assert.match(d.querySelector('#scan-output').textContent,/МИНУЛІ СВІЧКИ/);
  assert.match(d.querySelector('#scan-output').textContent,/НЕ створює торговий сигнал/);
  assert.equal(w.cryptoMyshkaPocket.getScreenshotHypothesis(),null);
  assert.equal(w.cryptoMyshkaPocket.getAnalysisState().localReport.kind,'historical_only');
  assert.equal(w.cryptoMyshkaPocket.getAnalysisState().localReport.direction,'down');
  assert.equal(d.querySelector('#ticket-offline-result').hidden,false);
  assert.match(d.querySelector('#ticket-offline-result').textContent,/минулі/i);
  assert.match(d.querySelector('#ticket-offline-result').textContent,/Не дає BUY\/SELL/);
  const callsBeforeLocal=requests.length;
  press('#ticket-guide-action');
  assert.equal(requests.length,callsBeforeLocal,
    'local mode must not call any paid AI provider');
  visionProblem=null;
  // Changing credentials must clear the previous result rather than keep glowing.
  d.querySelector('#cloud-access').value='new-access-code';
  d.querySelector('#cloud-access').dispatchEvent(new w.Event('input',{bubbles:true}));
  assert.match(d.querySelector('#ai-direction').textContent,/ЛОКАЛЬНО/);
  assert.equal(w.cryptoMyshkaPocket.getScreenshotHypothesis(),null);
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),false);
  assert.equal(requests.some(r=>String(r.url).includes('bybit')||String(r.url).includes('binance')||String(r.url).includes('pocketoption.com')),false);

  // Optional browser model must not fake capabilities or call a paid provider.
  const networkBeforeLocal=requests.length;
  press('#local-ai-vision');
  await new Promise(resolve=>setTimeout(resolve,15));
  assert.match(d.querySelector('#local-ai-status').textContent,/не підтримує вбудований AI/);
  assert.equal(requests.length,networkBeforeLocal);
  w.LanguageModel={
    availability:async()=> 'available',
    create:async()=>({
      prompt:async(input)=>{
        assert.equal(input[0].content[1].type,'image');
        return JSON.stringify({readable:true,direction:'DOWN',
          reason:'The last candles have lower observed highs and short downward slope.',
          risk:'The trend could reverse abruptly during a short expiry.',
          observations:['The recent candles show lower highs','The recent slope is downward']});
      },
      destroy(){}
    })
  };
  press('#local-ai-vision');
  await new Promise(resolve=>setTimeout(resolve,30));
  const localVision=w.cryptoMyshkaPocket.getScreenshotHypothesis();
  assert.ok(localVision,'on-device model must produce a separate hypothesis');
  assert.equal(localVision.source,'pocket_browser_hypothesis');
  assert.equal(localVision.direction,'DOWN');
  assert.equal(localVision.signal_validated,false);
  assert.equal(d.querySelector('#ticket-sell').classList.contains('jev-flash'),true);
  assert.equal(d.querySelector('#ticket-buy').classList.contains('jev-flash'),false);
  assert.match(d.querySelector('#ai-direction').textContent,/AI на ПК/);
  assert.match(d.querySelector('#local-ai-status').textContent,/без APInex/);
  assert.equal(requests.length,networkBeforeLocal,'device AI must not call cloud');

  console.log('Pocket UI: photo local analysis, genuine optional Chrome AI, quota failure, paper journal and demo-only flash OK');
  dom.window.close();
}
main().catch(e=>{console.error(e);process.exit(1);});
