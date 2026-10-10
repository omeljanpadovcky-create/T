/* Browser smoke for Pocket Lab. Run after npm install --no-save jsdom@26.1.0 */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {JSDOM}=require('jsdom');
async function main(){
  const root=path.resolve(__dirname,'..');
  const html=fs.readFileSync(path.join(root,'myshka-app.html'),'utf8');
  const script=fs.readFileSync(path.join(root,'app/pocket-option.js'),'utf8');
  const dom=new JSDOM(html,{url:'https://omeljanpadovcky-create.github.io/T/myshka-app.html#analysis',
    pretendToBeVisual:true,runScripts:'outside-only'});
  const w=dom.window,d=w.document;
  w.scrollTo=()=>{};
  w.confirm=()=>true;
  w.cryptoMyshkaPhotoScan={
    findChartBounds:()=>({x:20,y:15,w:330,h:185}),
    analyzePixels:()=>({recognized:true,visualDirection:'down',candidates:25,observedDirection:'Пізніші свічки нижче'})
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
  w.fetch=async (url,opts={})=>{
    requests.push({url:String(url),opts});
    if(String(url).endsWith('/api/chart-health'))
      return {ok:true,status:200,json:async()=>({ready:true,provider:'gemini',
        model:'gemini-2.5-flash-lite',verified:false})};
    if(String(url).endsWith('/api/pocket-vision')){
      if(!opts.method)return {ok:false,status:405,json:async()=>({error:'POST only'})};
      const body=JSON.parse(opts.body);
      assert.equal(body.pair,'EUR/USD OTC');
      assert.equal(body.chart_timeframe_seconds,60);
      assert.equal(body.expiry_seconds,60);
      assert.equal(body.payout_pct,92);
      assert.equal(body.image.startsWith('/9j/'),true);
      return {ok:true,status:200,json:async()=>({
        mode:'screenshot_hypothesis',direction:'UP',reason:'Два індикатори узгоджені, але це лише гіпотеза з фото.',
        risk:'Несподіваний розворот може призвести до втрати всієї ставки.',
        provider:'gemini',model:'test'
      })};
    }
    throw Error('Unexpected URL: '+url);
  };
  w.eval(script);
  await new Promise(r=>setTimeout(r,20));
  assert.equal(d.querySelectorAll('.mobile-nav button').length,5);
  assert.equal(d.querySelector('#pocket-pair').value,'EUR/USD OTC');
  assert.equal(d.querySelector('#pocket-expiry').value,'60');
  assert.equal(d.querySelector('#pocket-timeframe').value,'60');
  assert.match(d.querySelector('#pocket-math').textContent,/52,08/);
  assert.doesNotMatch(d.querySelector('#screen-analysis').textContent,/Bybit V5|Master Traders|TSLAUSDT/);
  assert.equal(d.querySelector('#screen-analysis').hidden,false);
  const press=sel=>{const el=d.querySelector(sel);assert.ok(el,sel);el.click();return el;};
  press('.mobile-nav [data-go="history"]');
  assert.equal(d.querySelector('#screen-history').hidden,false);
  press('.mobile-nav [data-go="analysis"]');
  d.querySelector('#cloud-endpoint').value='https://t-zeta-ashy.vercel.app';
  d.querySelector('#cloud-access').value='a'.repeat(32);
  press('#cloud-connect');
  await new Promise(r=>setTimeout(r,20));
  assert.match(d.querySelector('#cloud-indicator').textContent,/Pocket API та .* підключено/);
  const png=w.document.createElement('input');
  const fake=new w.File([new Uint8Array([137,80,78,71,13,10,26,10,...new Array(300).fill(1)])],
    'pocket.png',{type:'image/png'});
  // Trigger the same handler as Ctrl+V: jsdom provides FileReader and ClipboardEvent data.
  const event=new w.Event('paste',{bubbles:true,cancelable:true});
  Object.defineProperty(event,'clipboardData',{value:{items:[{type:'image/png',getAsFile:()=>fake}]}});
  d.dispatchEvent(event);
  await new Promise(r=>setTimeout(r,75));
  assert.equal(d.querySelector('#photo-stage').hidden,false);
  assert.equal(d.querySelector('#run-pocket-ai').disabled,false);
  press('#scan-pixels');
  assert.match(d.querySelector('#scan-output').textContent,/МИНУЛІ СВІЧКИ/);
  assert.match(d.querySelector('#scan-output').textContent,/Падіння вже на фото/);
  assert.match(d.querySelector('#ai-direction').textContent,/СТОП/);
  press('#run-pocket-ai');
  await new Promise(r=>setTimeout(r,30));
  assert.equal(usedCrop,true);
  assert.match(d.querySelector('#ai-direction').textContent,/ВГОРУ/);
  press('#save-paper');
  assert.equal(JSON.parse(w.localStorage.getItem('crypto-myshka-pocket-paper-v1')).length,1);
  press('.mobile-nav [data-go="history"]');
  assert.match(d.querySelector('#journal-list').textContent,/EUR\/USD OTC/);
  assert.match(d.querySelector('#journal-list').textContent,/Очікує|очікує/);
  assert.equal(requests.some(r=>String(r.url).includes('bybit')||String(r.url).includes('binance')),false);
  console.log('Pocket Option UI: navigation, payout, image crop, local scan, cloud hypothesis and journal OK');
  dom.window.close();
}
main().catch(e=>{console.error(e);process.exitCode=1;});
