/* Public, keyless, read-only Bybit V5 analysis. Not AI and not screenshot OCR. */
(() => {
  'use strict';
  const input=document.getElementById('bybit-fast-symbol');
  const timeframe=document.getElementById('bybit-fast-interval');
  const button=document.getElementById('bybit-fast-analyze');
  const status=document.getElementById('bybit-fast-status');
  const output=document.getElementById('bybit-fast-output');
  if(!input||!timeframe||!button||!status||!output)return;
  const allowedIntervals={'1':1,'5':5,'15':15,'30':30,'60':60,'240':240};
  const number=n=>Number.isFinite(n)?n.toLocaleString('uk-UA',{maximumFractionDigits:5}):'—';
  const pct=n=>Number.isFinite(n)?(n>0?'+':'')+n.toFixed(2)+'%':'—';
  let pending=false;
  let lastController=null;
  let latestReport=null;
  function emitReport(value){
    latestReport=value;
    window.dispatchEvent(new CustomEvent('crypto-myshka-market',{detail:value}));
  }
  const normalizeSymbol=raw=>String(raw||'').toUpperCase().replace(/[\s/]/g,'').trim();
  function appendLine(title,value,detail){
    const section=document.createElement('div');
    section.className='public-analysis-metric';
    const label=document.createElement('span');
    label.textContent=title;
    const strong=document.createElement('strong');
    strong.textContent=value;
    section.append(label,strong);
    if(detail){const small=document.createElement('small');small.textContent=detail;section.appendChild(small);}
    return section;
  }
  function ema(values,period){
    if(values.length<period) return null;
    let previous=values.slice(0,period).reduce((a,b)=>a+b,0)/period;
    const weight=2/(period+1);
    for(let i=period;i<values.length;i++)previous+=weight*(values[i]-previous);
    return previous;
  }
  function rsi(values){
    if(values.length<16)return null;
    let gain=0,loss=0;
    for(let i=1;i<=14;i++){
      const change=values[i]-values[i-1];
      gain+=Math.max(0,change);
      loss+=Math.max(0,-change);
    }
    gain/=14;loss/=14;
    for(let i=15;i<values.length;i++){
      const change=values[i]-values[i-1];
      gain=(gain*13+Math.max(0,change))/14;
      loss=(loss*13+Math.max(0,-change))/14;
    }
    return gain===0&&loss===0?50:loss===0?100:100-100/(1+gain/loss);
  }
  function parseCompletedCandles(payload,intervalMinutes){
    if(payload?.retCode!==0||!Array.isArray(payload.result?.list))
      throw new Error(payload?.retMsg ? 'Bybit: '+String(payload.retMsg).slice(0,130) : 'Bybit не повернув коректні свічки.');
    const now=Date.now();
    const rows=payload.result.list.map(r=>({
      start:Number(r[0]),open:Number(r[1]),high:Number(r[2]),low:Number(r[3]),
      close:Number(r[4]),volume:Number(r[5])
    })).filter(c=>Object.values(c).every(Number.isFinite) &&
      c.start>0 && c.open>0 && c.close>0 && c.high>=Math.max(c.open,c.close,c.low) &&
      c.low>0 && c.start+intervalMinutes*60000<=now-1500)
      .sort((a,b)=>a.start-b.start);
    const unique=new Map(rows.map(c=>[c.start,c]));
    const completed=[...unique.values()].sort((a,b)=>a.start-b.start);
    if(completed.length<35)throw new Error('Для цього інструмента менше 35 завершених свічок. Статистику не вигадуємо.');
    return completed;
  }
  function calculate(candles){
    const closes=candles.map(c=>c.close);
    const last=candles[candles.length-1],prior=candles[candles.length-2];
    const ma9=ema(closes,9),ma21=ema(closes,21),rsi14=rsi(closes);
    const recent=candles.slice(-20),near=candles.slice(-10);
    const support=Math.min(...recent.map(c=>c.low));
    const resistance=Math.max(...recent.map(c=>c.high));
    const avgVolume=recent.reduce((a,c)=>a+c.volume,0)/recent.length;
    const volumeRatio=avgVolume>0?last.volume/avgVolume:null;
    const nearRange=100*(Math.max(...near.map(c=>c.high))-Math.min(...near.map(c=>c.low)))/last.close;
    const emaGap=100*(ma9-ma21)/last.close;
    const singleChange=100*(last.close/prior.close-1);
    const last5=candles[candles.length-6];
    const fiveChange=100*(last.close/last5.close-1);
    const consolidation=Math.abs(emaGap)<0.45 && nearRange<2.4;
    const regime=consolidation?'Локальна консолідація / вузький рух'
      : ma9>ma21?'EMA 9 вище EMA 21 (висхідний нахил)'
      : ma9<ma21?'EMA 9 нижче EMA 21 (спадний нахил)'
      :'Рух без стійкого нахилу';
    const volumeNote=volumeRatio===null?'Обсяг недоступний'
      :volumeRatio>=1.4?'Обсяг останньої свічки вищий за середній'
      :volumeRatio<0.75?'Обсяг останньої свічки нижчий за середній'
      :'Обсяг поблизу середнього';
    return {last,ma9,ma21,rsi14,support,resistance,volumeRatio,nearRange,singleChange,fiveChange,regime,volumeNote,completed: candles.length};
  }
  function showAnalysis(symbol,minutes,calc,ticker){
    output.replaceChildren();
    const summary=document.createElement('div');
    summary.className='public-analysis-summary';
    const tag=document.createElement('strong');tag.textContent=symbol+' · '+minutes+' хв · завершені свічки';
    const verdict=document.createElement('p');verdict.textContent=calc.regime;
    const observed=document.createElement('small');
    const at=new Date(calc.last.start+minutes*60000);
    observed.textContent='Останнє закриття: '+at.toLocaleString('uk-UA')+' · '+calc.completed+' свічок із Bybit V5';
    summary.append(tag,verdict,observed);output.appendChild(summary);
    const grid=document.createElement('div');grid.className='public-analysis-grid';
    const stats=[
      ['Останнє закриття',number(calc.last.close)+' USDT','Попередня завершена свічка: '+pct(calc.singleChange)],
      ['EMA 9 / EMA 21',number(calc.ma9)+' / '+number(calc.ma21),calc.regime],
      ['RSI 14',number(calc.rsi14),calc.rsi14>=70?'Високі значення RSI':calc.rsi14<=30?'Низькі значення RSI':'Середній діапазон RSI'],
      ['Мінімум 20 свічок',number(calc.support)+' USDT','Орієнтир підтримки, не гарантований рівень'],
      ['Максимум 20 свічок',number(calc.resistance)+' USDT','Орієнтир опору, не гарантований рівень'],
      ['Обсяг / середній 20',calc.volumeRatio===null?'—':number(calc.volumeRatio)+'×',calc.volumeNote],
      ['Рух 5 свічок',pct(calc.fiveChange),'Історична зміна, не прогноз'],
      ['Діапазон 10 свічок',pct(calc.nearRange),'Розмах високих і низьких цін']
    ];
    for(const [name,value,detail] of stats)grid.appendChild(appendLine(name,value,detail));
    output.appendChild(grid);
    if(ticker && Number.isFinite(Number(ticker.lastPrice))){
      const box=document.createElement('p');box.className='public-analysis-note';
      box.textContent='Поточна ціна Bybit: '+number(Number(ticker.lastPrice))+' USDT. Вона може відрізнятися від останнього завершеного закриття.';
      output.appendChild(box);
    }
    const caution=document.createElement('p');caution.className='public-analysis-note';
    caution.textContent='Це автоматичний математичний огляд офіційних OHLCV, НЕ розпізнавання скріншота, НЕ AI, НЕ статистика трейдера і НЕ рекомендація відкривати угоду. На основі цих показників неможливо надійно передбачити напрямок.';
    output.appendChild(caution);
  }
  async function requestJson(url,controller){
    const response=await fetch(url,{cache:'no-store',signal:controller.signal,headers:{Accept:'application/json'}});
    if(!response.ok)throw new Error('Bybit HTTP '+response.status);
    return response.json();
  }
  async function run(){
    if(pending)return;
    const symbol=normalizeSymbol(input.value);
    const interval=String(timeframe.value);
    if(!/^[A-Z0-9]{3,22}$/.test(symbol) || !Object.hasOwn(allowedIntervals,interval)){
      status.textContent='Вкажи коректну пару (наприклад TSLAUSDT або BTCUSDT) і таймфрейм.';
      return;
    }
    input.value=symbol;
    try{localStorage.setItem('crypto-myshka-public-symbol',symbol);}catch{}
    try{localStorage.setItem('crypto-myshka-public-interval',interval);}catch{}
    pending=true;button.disabled=true;
    emitReport(null);
    status.textContent='⏳ Отримуємо '+symbol+' · '+allowedIntervals[interval]+' хв із Bybit…';
    output.textContent='Завантажуємо тільки публічні свічки. AI-код не потрібен.';
    const controller=new AbortController();lastController=controller;
    const timer=setTimeout(()=>controller.abort(),13000);
    try{
      const host='https://api.bybit.com';
      const url=host+'/v5/market/kline?category=linear&symbol='+encodeURIComponent(symbol)+'&interval='+interval+'&limit=110';
      const payload=await requestJson(url,controller);
      const candles=parseCompletedCandles(payload,allowedIntervals[interval]);
      const calc=calculate(candles);
      let ticker=null;
      try{
        const t=await requestJson(host+'/v5/market/tickers?category=linear&symbol='+encodeURIComponent(symbol),controller);
        if(t.retCode===0)ticker=t.result?.list?.find(x=>x.symbol===symbol)||null;
      }catch{}
      emitReport(Object.freeze({
        source:'bybit_v5_market_kline',verifiedMarketFeed:true,symbol,
        intervalMinutes:allowedIntervals[interval],
        lastClosedAt:new Date(calc.last.start+allowedIntervals[interval]*60000).toISOString(),
        completedCandles:calc.completed,observedAt:new Date().toISOString(),
        indicators:{
          lastClose:calc.last.close,ema9:calc.ma9,ema21:calc.ma21,rsi14:calc.rsi14,
          support:calc.support,resistance:calc.resistance,volumeRatio:calc.volumeRatio,
          range10Pct:calc.nearRange,change1Pct:calc.singleChange,change5Pct:calc.fiveChange,
          regime:calc.regime,volumeNote:calc.volumeNote
        },
        currentTicker:Number.isFinite(Number(ticker?.lastPrice))&&ticker?Number(ticker.lastPrice):null,
        positionsVerified:false,ordersEnabled:false
      }));
      showAnalysis(symbol,allowedIntervals[interval],calc,ticker);
      status.textContent='✅ Огляд побудовано за '+calc.completed+' завершеними свічками · '+new Date().toLocaleTimeString('uk-UA')+' · без JEV';
    }catch(e){
      const reason=e.name==='AbortError'?'тайм-аут запиту до Bybit':String(e.message||'API недоступний');
      status.textContent='⚠️ Не вдалося отримати підтверджені свічки '+symbol+'.';
      output.textContent='Bybit API: '+reason+'. Перевір назву контракту або спробуй BTCUSDT. Жодних даних, трендів чи прибутків не вигадуємо.';
    }finally{clearTimeout(timer);pending=false;button.disabled=false;lastController=null;}
  }
  button.addEventListener('click',run);
  input.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();run();}});
  const picker=document.getElementById('pair-search');
  // Search field is distinct from Bybit symbol selection: do not silently change
  // contract and mistake an OTC or non-Bybit instrument for an official ticker.
  try {
    const saved=localStorage.getItem('crypto-myshka-public-symbol');
    const prior=localStorage.getItem('crypto-myshka-public-interval');
    const migration='crypto-myshka-public-default-btc5-v1';
    // Older releases auto-saved TSLA/30 as a default without user intent.
    // Migrate only that exact old default once, preserving other manual choices.
    if (!localStorage.getItem(migration) && saved==='TSLAUSDT' && prior==='30') {
      input.value='BTCUSDT'; timeframe.value='5';
      localStorage.setItem('crypto-myshka-public-symbol','BTCUSDT');
      localStorage.setItem('crypto-myshka-public-interval','5');
    } else {
      if (saved && /^[A-Z0-9]{3,22}$/.test(saved)) input.value=saved;
      if (prior && Object.hasOwn(allowedIntervals,prior)) timeframe.value=prior;
    }
    localStorage.setItem(migration,'true');
  } catch {}
  window.cryptoMyshkaPublicAnalysis={
    run,
    getLastReport(){return latestReport;},
    selectMarket({symbol,interval='5',analyze=false}={}) {
      const normalized=normalizeSymbol(String(symbol||''));
      if (!/^[A-Z0-9]{3,22}$/.test(normalized) || !Object.hasOwn(allowedIntervals,String(interval))) return false;
      input.value=normalized; timeframe.value=String(interval);
      if (analyze) run();
      return true;
    },
    selectSymbol(symbol){
      const normalized=normalizeSymbol(symbol);
      if(/^[A-Z0-9]{3,22}$/.test(normalized))input.value=normalized;
    }
  };
  run();
})();