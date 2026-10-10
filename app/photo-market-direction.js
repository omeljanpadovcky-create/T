/* Bybit closed-candle direction near user-uploaded screenshot.
 * Read-only independent market data, never infers photo symbol or predicts the next candle.
 * Uses only public Bybit V5 spot/linear endpoints; no secrets, orders or AI provider.
 */
(() => {
  'use strict';
  const ALLOWED_INTERVALS = new Set(['1','5','15','30','60','240']);
  const ALLOWED_CATEGORIES = new Set(['spot','linear']);
  const normalize = v => String(v || '').toUpperCase().replace(/[\s/]/g,'').trim();
  const percent = v => (v>=0?'+':'')+v.toFixed(3)+'%';
  const formatPrice = n => Number(n).toLocaleString('uk-UA',{maximumFractionDigits:6});

  // Transparent heuristic, not AI or a validated prediction. Features use only
  // completed candles up to index i. The next-candle result is never used to score it.
  function vote(candles,index){
    if(index<26)return {bias:'unknown',score:0,reasons:[]};
    const rows=candles.slice(0,index+1),closes=rows.map(x=>x.close),last=rows[rows.length-1];
    function ema(period){
      let value=closes.slice(0,period).reduce((a,b)=>a+b,0)/period;
      for(let i=period;i<closes.length;i++)value+=2/(period+1)*(closes[i]-value);
      return value;
    }
    let tr=0;
    for(let k=rows.length-14;k<rows.length;k++){
      const row=rows[k],previous=rows[k-1].close;
      tr+=Math.max(row.high-row.low,Math.abs(row.high-previous),Math.abs(row.low-previous));
    }
    const atr=tr/14;
    if(!(atr>0))return {bias:'unknown',score:0,reasons:[]};
    let gain=0,loss=0;
    for(let k=closes.length-14;k<closes.length;k++){
      const diff=closes[k]-closes[k-1];
      gain+=Math.max(diff,0);loss+=Math.max(-diff,0);
    }
    const rsi=gain===0&&loss===0?50:loss===0?100:100-100/(1+gain/loss);
    const classify=(change,min)=>change>min?1:change< -min?-1:0;
    const components=[
      ['EMA 9/21',classify(ema(9)-ema(21),atr*.1)],
      ['Імпульс 3 свічок',classify(last.close-rows[rows.length-4].close,atr*.25)],
      ['RSI 14',classify(rsi-50,5)],
      ['Тіло останньої свічки',classify(last.close-last.open,atr*.12)]
    ];
    const score=components.reduce((s,p)=>s+p[1],0);
    const active=components.filter(p=>p[1]!==0).length;
    return {
      bias:active>=3&&Math.abs(score)>=3?(score>0?'up':'down'):'unknown',
      score,
      reasons:components.map(([name,v])=>name+': '+(v>0?'↑':v<0?'↓':'—'))
    };
  }
  function evaluate(candles){
    const recent=vote(candles,candles.length-1);
    let tries=0,hits=0,skipped=0;
    for(let i=Math.max(26,candles.length-61);i<candles.length-1;i++){
      const observation=vote(candles,i);
      const old=candles[i].close,next=candles[i+1].close;
      if(observation.bias==='unknown'||Math.abs(next/old-1)<.00005){skipped++;continue;}
      tries++;
      if((next>old)===(observation.bias==='up'))hits++;
    }
    return {bias:recent.bias,score:recent.score,reasons:recent.reasons,
      trials:tries,hits,misses:tries-hits,skipped,
      observedAccuracy:tries?100*hits/tries:null};
  }
  function review(payload, symbol, interval, category, now=Date.now()){
    if(!ALLOWED_INTERVALS.has(String(interval))||!ALLOWED_CATEGORIES.has(category))
      throw new Error('Непідтримуваний тип ринку або таймфрейм.');
    if(payload?.retCode!==0 || !Array.isArray(payload?.result?.list))
      throw new Error('Bybit не повернув підтверджені свічки: '+String(payload?.retMsg||'невідома помилка').slice(0,100));
    if(payload.result.symbol && payload.result.symbol!==symbol)
      throw new Error('Bybit повернув іншу торгову пару — аналіз зупинено.');
    if(payload.result.category && payload.result.category!==category)
      throw new Error('Bybit повернув інший тип ринку — аналіз зупинено.');
    const minutes=Number(interval);
    const candles=new Map();
    for(const row of payload.result.list){
      const start=Number(row[0]),open=Number(row[1]),high=Number(row[2]),low=Number(row[3]),close=Number(row[4]);
      if(![start,open,high,low,close].every(Number.isFinite)||start<=0||low<=0||open<=0||
         close<=0||high<Math.max(open,close,low)||start+minutes*60000>now-1500)continue;
      candles.set(start,{start,open,high,low,close});
    }
    const completed=[...candles.values()].sort((a,b)=>a.start-b.start);
    if(completed.length<6)throw new Error('Недостатньо завершених свічок для порівняння.');
    const recent=completed.slice(-6),first=recent[0],last=recent[5];
    // We do not substitute old market history for the user's current chart.
    const age=now-(last.start+minutes*60000);
    if(age>minutes*60000*3)
      throw new Error('Дані Bybit застарілі. Онови пізніше.');
    const delta=100*(last.close/first.close-1);
    const direction=Math.abs(delta)<.005?'unknown':delta>0?'up':'down';
    return {symbol,category,intervalMinutes:minutes,completedCount:completed.length,
      direction,changePct:delta,
      scenario:evaluate(completed),
      firstClose:first.close,lastClose:last.close,
      lastClosedAt:new Date(last.start+minutes*60000).toISOString(),
      source:'Bybit V5 /v5/market/kline',notScreenshot:true,
      isPrediction:false,tradingEnabled:false};
  }

  function create(tag,cssText,textContent){
    const el=document.createElement(tag);
    if(cssText)el.style.cssText=cssText;
    if(textContent)el.textContent=textContent;
    return el;
  }
  function attach({container}){
    if(!container)return;
    const panel=create('section','padding:14px;margin:12px 0;border:1px solid #64748b;border-radius:14px;overflow:hidden;');
    panel.className='screenshot-market-direction';
    const heading=create('h3','margin:0 0 6px','📈 ВГОРУ / ВНИЗ із реальних свічок');
    const info=create('p','font-size:13px;line-height:1.55;margin:0 0 12px',
      'Якщо фото містить індикатор або сканер не впізнав свічки, обери ту саму пару та тип ринку, що на графіку. Це ОКРЕМИЙ аналіз завершених свічок Bybit, а НЕ розпізнавання завантаженого фото. OTC та інші біржі можуть мати інші ціни.');
    const controls=create('div','display:flex;gap:8px;flex-wrap:wrap;align-items:end');
    function field(title,control){
      const label=create('label','display:flex;flex-direction:column;gap:5px;min-width:104px;flex:1;font-size:12px',title);
      control.style.cssText='width:100%;font-size:14px;min-height:39px;border-radius:8px;padding:8px;background:transparent;border:1px solid #8ea3bb;color:inherit';
      label.appendChild(control);controls.appendChild(label);
      return control;
    }
    const symbol=document.createElement('input');
    symbol.type='text';symbol.value='BTCUSDT';symbol.maxLength=22;
    symbol.autocomplete='off';symbol.spellcheck=false;
    field('Пара на фото',symbol);
    const category=document.createElement('select');
    for(const [value,label] of [['spot','Spot'],['linear','Ф’ючерси (linear)']]){
      const option=document.createElement('option');option.value=value;option.textContent=label;category.appendChild(option);
    }
    category.value='spot';
    field('Тип ринку',category);
    const timeframe=document.createElement('select');
    for(const [value,label] of [['1','1 хв'],['5','5 хв'],['15','15 хв'],['30','30 хв'],['60','1 год'],['240','4 год']]){
      const option=document.createElement('option');option.value=value;option.textContent=label;timeframe.appendChild(option);
    }
    timeframe.value='30';field('Свічка',timeframe);
    const button=create('button','','↻ Показати напрям');
    button.type='button';button.className='small-button';
    button.style.margin='10px 0';
    const status=create('p','font-size:12px;line-height:1.5','Оберіть пару, яка справді показана на фото, і натисніть кнопку.');
    status.setAttribute('role','status');
    status.setAttribute('aria-live','polite');
    const result=create('div','','');
    result.setAttribute('aria-live','polite');
    let currentController=null;
    function render(answer){
      result.replaceChildren();
      const labels={up:'↑ ВГОРУ',down:'↓ ВНИЗ',unknown:'— БЕЗ ЧІТКОГО РУХУ'};
      const big=create('div','font-size:clamp(27px,5vw,42px);font-weight:850;line-height:1.25;margin:10px 0',
        labels[answer.direction]);
      big.style.color=answer.direction==='up'?'#16a34a':answer.direction==='down'?'#f87171':'inherit';
      const caption=create('p','font-size:13px;white-space:pre-wrap;line-height:1.6',
        answer.symbol+' · '+(answer.category==='spot'?'Spot':'Linear')+' · '+answer.intervalMinutes+' хв\n'+
        'Останні 5 завершених свічок: '+percent(answer.changePct)+'\n'+
        'Закриття: '+formatPrice(answer.firstClose)+' → '+formatPrice(answer.lastClose)+' USDT\n'+
        'Остання закрита свічка: '+new Date(answer.lastClosedAt).toLocaleString('uk-UA')+'\n'+
        'Джерело: офіційний Bybit V5 /market/kline');
      const caution=create('p','font-size:12px;line-height:1.5;color:inherit',
        'Це ВЖЕ ВІДОМИЙ рух завершених свічок вибраної пари. Не прогноз, не AI, не сигнал для ставки. '+
        'Якщо фото з іншої біржі, OTC чи іншого часу, результат може не відповідати скріншоту.');
      result.append(big,caption,caution);
    }
    button.addEventListener('click',async ()=>{
      const pair=normalize(symbol.value);
      const market=category.value,period=timeframe.value;
      if(!/^[A-Z0-9]{3,22}$/.test(pair)||!ALLOWED_CATEGORIES.has(market)||!ALLOWED_INTERVALS.has(period)){
        status.textContent='Перевір назву пари, ринок і таймфрейм.';
        result.replaceChildren();return;
      }
      if(currentController)currentController.abort();
      const controller=new AbortController();currentController=controller;
      const timer=setTimeout(()=>controller.abort(),14000);
      button.disabled=true;
      result.replaceChildren();
      status.textContent='⏳ Читаємо завершені свічки '+pair+' · '+market+' · '+period+' хв…';
      try{
        const url='https://api.bybit.com/v5/market/kline?category='+encodeURIComponent(market)+
          '&symbol='+encodeURIComponent(pair)+'&interval='+encodeURIComponent(period)+'&limit=80';
        const res=await fetch(url,{cache:'no-store',signal:controller.signal,headers:{Accept:'application/json'}});
        if(!res.ok)throw new Error('Bybit HTTP '+res.status);
        const data=await res.json();
        const verdict=review(data,pair,period,market);
        if(!panel.isConnected)return;
        render(verdict);
        status.textContent='✅ Напрям останніх 5 завершених свічок отримано без AI.';
      }catch(e){
        if(!panel.isConnected)return;
        status.textContent=e?.name==='AbortError'?'⚠️ Час очікування Bybit минув.':
          '⚠️ Не вдалося підтвердити напрям: '+String(e?.message||'дані недоступні').slice(0,180);
        result.replaceChildren();
      }finally{
        clearTimeout(timer);
        if(currentController===controller){currentController=null;button.disabled=false;}
      }
    });
    panel.append(heading,info,controls,button,status,result);
    container.appendChild(panel);
  }
  window.cryptoMyshkaPhotoMarket={attach,review};
})();