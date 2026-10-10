/* Old CryptoMyshka dashboard: secure opt-in JEV chat + chart observer.
 * The server key remains in Vercel; per-tab access token stays in sessionStorage.
 * Public Bybit market fallback is deterministic context, NOT AI inference.
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const URL_KEY='crypto-myshka-cloud-endpoint-v1';
  const ACCESS_KEY='crypto-myshka-cloud-access-session-v1';
  const DEFAULT_URL='https://t-zeta-ashy.vercel.app';
  let root='',access='',selectedFile=null,previewUrl=null,market=null,history=[];
  const formatter=n=>Number.isFinite(n)?n.toLocaleString('uk-UA',{maximumFractionDigits:4}):'—';
  function allowedUrl(value){
    try{
      const u=new URL(String(value).trim());
      return u.protocol==='https:' && !u.username && !u.password && u.pathname==='/' && !u.search && !u.hash ? u.origin : '';
    }catch{return '';}
  }
  function configured(){return !!root && access.length>=24;}
  function put(id,text){const el=$(id);if(el)el.textContent=text;}
  function setState(text){put('legacy-jev-status',text);put('mouseJevState',text);}
  function showConnection(){
    const panel=$('legacy-jev-connection');
    if(panel)panel.hidden=!panel.hidden;
    if(panel && !panel.hidden)$('legacy-jev-access')?.focus();
  }
  function refreshAuth(){
    root=allowedUrl(localStorage.getItem(URL_KEY)||'') || DEFAULT_URL;
    access=sessionStorage.getItem(ACCESS_KEY)||'';
    $('legacy-jev-endpoint').value=root;
    $('legacy-jev-access').value=access;
    setState(configured()?'🔑 Код JEV є в цій вкладці · перевірити AI запитом':'🔑 Підключи JEV для справжнього AI · ринковий огляд доступний без ключа');
    $('legacy-jev-connection').hidden=configured();
  }
  async function send(path,body,timeoutMs=35000){
    if(!configured())throw new Error('Підключи сервер та введи свій код доступу JEV.');
    const ctrl=new AbortController();
    const timeout=setTimeout(()=>ctrl.abort(),timeoutMs);
    try{
      const r=await fetch(root+path,{
        method:'POST',headers:{'Content-Type':'application/json','X-JEV-Access':access},
        body:JSON.stringify(body),cache:'no-store',credentials:'omit',signal:ctrl.signal
      });
      const result=await r.json().catch(()=>({}));
      if(!r.ok)throw new Error(
        (r.status===402||/HTTP\s*402\b/.test(String(result.error||'')))
          ? 'HTTP 402: AI-провайдер обмежив аналіз за квотою/балансом. Безкоштовний огляд Bybit працює окремо.'
          : String(result.error||'JEV: HTTP '+r.status).slice(0,240)
      );
      return result;
    }catch(e){
      if(e?.name==='AbortError')throw new Error('JEV не відповів за '+Math.round(timeoutMs/1000)+' секунд.');
      throw e;
    }finally{clearTimeout(timeout)}
  }
  async function connect(){
    const endpoint=allowedUrl($('legacy-jev-endpoint').value);
    const token=$('legacy-jev-access').value.trim();
    if(!endpoint||token.length<24){setState('Адреса HTTPS без шляху й код JEV щонайменше 24 символи.');return;}
    root=endpoint;access=token;
    try{localStorage.setItem(URL_KEY,root);sessionStorage.setItem(ACCESS_KEY,access);}
    catch{setState('Браузер не зберіг налаштування: доступ лише в цій вкладці.');}
    setState('⏳ Перевіряємо JEV…');
    $('legacy-jev-connect').disabled=true;
    try{
      const ctrl=new AbortController(),t=setTimeout(()=>ctrl.abort(),12000);
      let r;try{r=await fetch(root+'/api/chart-health',{headers:{'X-JEV-Access':access},signal:ctrl.signal,cache:'no-store'});}finally{clearTimeout(t)}
      const health=await r.json().catch(()=>({}));
      if(!r.ok||health.ready!==true)throw new Error(health.error||'JEV: HTTP '+r.status);
      setState('🟠 Сервер доступний · '+(health.model||health.provider||'AI')+' · справжній аналіз ще не перевірено');
      $('legacy-jev-connection').hidden=true;
    }catch(e){setState('⚠️ '+String(e.message||'Немає зв’язку з сервером').slice(0,180))}
    finally{$('legacy-jev-connect').disabled=false;}
  }
  function disconnect(){
    root='';access='';history=[];
    try{sessionStorage.removeItem(ACCESS_KEY);}catch{}
    $('legacy-jev-access').value='';
    $('legacy-jev-connection').hidden=false;
    setState('🔑 Код доступу прибрано з поточної вкладки. Публічні дані Bybit доступні.');
  }
  async function ask(message){
    const result=await send('/api/jev-chat',{message,history},35000);
    const answer=String(result.reply||'').trim();
    if(!answer)throw new Error('JEV повернув порожню відповідь.');
    history.push({role:'user',content:message.slice(0,1000)},{role:'assistant',content:answer.slice(0,1000)});
    history=history.slice(-6);
    setState('🟢 JEV відповів · '+(result.provider==='gemini'?'Gemini': 'APInex')+' · '+(result.model||'AI'));
    return {text:answer,model:result.model,provider:result.provider};
  }
  function marketDescription(pair){
    const ticker=market?.get(pair);
    if(!ticker)return null;
    const price=Number(ticker.lastPrice),change=100*Number(ticker.price24hPcnt);
    if(!Number.isFinite(price)||!Number.isFinite(change))return null;
    return pair.replace('USDT','')+' на Bybit ≈ '+formatter(price)+' USDT, '+(change>=0?'+':'')+formatter(change)+'% за 24 год. Це публічні котирування, НЕ торговий сигнал.';
  }
  function fallbackFor(message){
    const query=message.toUpperCase();
    for(const symbol of ['BTCUSDT','ETHUSDT','SOLUSDT']){
      if(query.includes(symbol.slice(0,-4))) {
        const quote=marketDescription(symbol);
        if(quote)return quote+'\nНемає підтвердженого прогнозу напрямку.';
      }
    }
    return '';
  }
  async function refreshMarket(){
    const btn=$('legacy-jev-market-refresh');
    btn.disabled=true;put('legacy-jev-market','Отримуємо котирування…');
    const ctrl=new AbortController(),t=setTimeout(()=>ctrl.abort(),12000);
    try{
      const response=await fetch('https://api.bybit.com/v5/market/tickers?category=linear',{cache:'no-store',signal:ctrl.signal});
      if(!response.ok)throw Error('HTTP '+response.status);
      const data=await response.json();
      if(data.retCode!==0||!Array.isArray(data.result?.list))throw Error('Bybit: недоступні дані');
      market=new Map(data.result.list.map(x=>[x.symbol,x]));
      const out=['BTCUSDT','ETHUSDT','SOLUSDT'].map(marketDescription).filter(Boolean);
      put('legacy-jev-market',out.join('\n')+'\nОновлено: '+new Date().toLocaleTimeString('uk-UA')+' · тільки публічний ринок.');
    }catch(e){put('legacy-jev-market','⚠️ Котирування Bybit тимчасово недоступні. '+e.message)}
    finally{clearTimeout(t);btn.disabled=false;}
  }
  function ema(values, span){
    const weight=2/(span+1);
    return values.reduce((prior,next,i)=>i===0?next:prior+weight*(next-prior),0);
  }
  function rsi14(values){
    if(values.length<16)return null;
    let up=0,down=0;
    for(let i=1;i<=14;i++){
      const delta=values[i]-values[i-1];
      up+=Math.max(delta,0);down+=Math.max(-delta,0);
    }
    up/=14;down/=14;
    for(let i=15;i<values.length;i++){
      const delta=values[i]-values[i-1];
      up=(up*13+Math.max(delta,0))/14;
      down=(down*13+Math.max(-delta,0))/14;
    }
    return down===0 ? (up===0?50:100) : 100-100/(1+up/down);
  }
  async function analyzePublicCandles(){
    const btn=$('legacy-jev-technical-button'),symbol=$('legacy-jev-symbol').value;
    if(!['BTCUSDT','ETHUSDT','SOLUSDT'].includes(symbol))return;
    btn.disabled=true;
    put('legacy-jev-technical','Отримуємо завершені 30-хвилинні свічки Bybit…');
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),12000);
    try{
      const url='https://api.bybit.com/v5/market/kline?category=linear&symbol='+encodeURIComponent(symbol)+'&interval=30&limit=80';
      const response=await fetch(url,{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw Error('HTTP '+response.status);
      const data=await response.json();
      if(data.retCode!==0||!Array.isArray(data.result?.list))throw Error('Немає коректного OHLCV');
      const candles=data.result.list.map(x=>({
        start:Number(x[0]),open:Number(x[1]),high:Number(x[2]),
        low:Number(x[3]),close:Number(x[4]),volume:Number(x[5])
      })).filter(x=>Object.values(x).every(Number.isFinite)&&x.start+1800000<=Date.now()).sort((a,b)=>a.start-b.start);
      if(candles.length<35)throw Error('Замало завершених свічок для аналізу.');
      const closes=candles.map(x=>x.close),last=candles[candles.length-1],e9=ema(closes,9),e21=ema(closes,21),r=rsi14(closes);
      const recent=candles.slice(-20),support=Math.min(...recent.map(x=>x.low)),resistance=Math.max(...recent.map(x=>x.high));
      const avgVolume=recent.reduce((n,x)=>n+x.volume,0)/recent.length;
      const ratio=avgVolume>0?last.volume/avgVolume:null;
      const regime=e9>e21?'EMA9 вище EMA21 (локально висхідний нахил)':e9<e21?'EMA9 нижче EMA21 (локально спадний нахил)':'EMA9 ≈ EMA21 (без нахилу)';
      put('legacy-jev-technical','BYBIT '+symbol+' · 30 хв · '+candles.length+' завершених свічок'+
        '\nЗакриття останньої: '+formatter(last.close)+' USDT · '+new Date(last.start+1800000).toLocaleString('uk-UA')+
        '\nEMA 9 / EMA 21: '+formatter(e9)+' / '+formatter(e21)+' USDT'+
        '\nЛокальна структура: '+regime+
        '\nRSI 14: '+(r===null?'—':formatter(r))+
        '\nМінімум/максимум 20 свічок: '+formatter(support)+' / '+formatter(resistance)+' USDT'+
        '\nОбсяг останньої свічки / середній 20: '+(ratio===null?'—':formatter(ratio)+'×')+
        '\n\nЦе розрахунки за офіційними свічками Bybit, НЕ AI, НЕ LIVE-позиції трейдерів і НЕ сигнал BUY/SELL.');
    }catch(e){
      put('legacy-jev-technical','⚠️ Технічний огляд недоступний: '+String(e.message||'Помилка API').slice(0,180)+
        '\nРеальні угоди й сигнали не створювалися.');
    }finally{clearTimeout(timer);btn.disabled=false;}
  }
  function readFile(file){
    selectedFile=null;
    if(previewUrl){URL.revokeObjectURL(previewUrl);previewUrl=null;}
    $('legacy-jev-preview').hidden=true;
    $('legacy-jev-analyze').disabled=true;
    if(!file)return;
    if(!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size>2*1024*1024||file.size<1){
      put('legacy-jev-result','Потрібне зображення JPG/PNG/WebP до 2 МБ.');return;
    }
    selectedFile=file;previewUrl=URL.createObjectURL(file);
    $('legacy-jev-preview').src=previewUrl;
    $('legacy-jev-preview').hidden=false;
    $('legacy-jev-analyze').disabled=false;
    put('legacy-jev-result','📷 '+file.name+' готовий. Для аналізу потрібен доступний AI. Саме зображення ще не надсилалося.');
  }
  async function analyzePhoto(){
    if(!selectedFile)return;
    if(!configured()){
      $('legacy-jev-connection').hidden=false;
      put('legacy-jev-result','🔑 Підключи JEV кодом доступу, щоб надіслати фото на свій сервер.');return;
    }
    const btn=$('legacy-jev-analyze');btn.disabled=true;
    put('legacy-jev-result','⏳ JEV аналізує завантажене фото…');
    try{
      const base64=await new Promise((resolve,reject)=>{
        const reader=new FileReader();
        reader.onerror=()=>reject(new Error('Не вдалося прочитати зображення.'));
        reader.onload=()=>resolve(String(reader.result||'').split(',')[1]);
        reader.readAsDataURL(selectedFile);
      });
      const out=await send('/api/chart-analysis',{image:base64,chart_timeframe:$('legacy-jev-timeframe').value},40000);
      const direction=['ВГОРУ','ВНИЗ','НЕВИЗНАЧЕНО'].includes(out.direction)?out.direction:'НЕВИЗНАЧЕНО';
      const action=['BUY','SELL'].includes(out.action)?out.action:'ПРОПУСТИТИ';
      put('legacy-jev-result','🤖 '+(out.provider||'AI')+' · '+(out.model||'JEV')+
        '\nВидимий напрямок: '+direction+'\nДемо-гіпотеза: '+action+
        '\nТаймфрейм: '+(out.chart_timeframe||'невідомий')+
        '\nПідстава: '+String(out.reason||'Недостатньо даних.').slice(0,250)+
        '\n⚠️ Фото — не LIVE, результат угоди не підтверджений. Жодних ордерів.');
      setState('🟢 JEV обробив фото · '+(out.provider||'AI'));
    }catch(e){
      put('legacy-jev-result','⛔ Фото НЕ проаналізоване. '+String(e.message||'Немає відповіді').slice(0,280));
    }finally{btn.disabled=false;}
  }
  function setup(){
    refreshAuth();
    $('legacy-jev-connect').addEventListener('click',connect);
    $('legacy-jev-disconnect').addEventListener('click',disconnect);
    $('legacy-jev-show-connection').addEventListener('click',showConnection);
    $('mouseJevConnect').addEventListener('click',()=>{
      const popup=$('mouseAiToggle');if(popup)popup.checked=false;
      document.querySelector('.tab[data-mode="chart"]')?.click();
      $('legacy-jev-connection').hidden=false;
      $('legacy-jev-access').focus();
      document.getElementById('legacy-jev-panel')?.scrollIntoView({behavior:'smooth'});
    });
    $('legacy-jev-market-refresh').addEventListener('click',refreshMarket);
    $('legacy-jev-technical-button').addEventListener('click',analyzePublicCandles);
    $('legacy-jev-file').addEventListener('change',e=>readFile(e.target.files?.[0]));
    $('legacy-jev-analyze').addEventListener('click',analyzePhoto);
    refreshMarket();
  }
  window.legacyJev={canChat:configured,ask,fallbackFor,showConnection,refreshMarket};
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',setup);
  else setup();
})();