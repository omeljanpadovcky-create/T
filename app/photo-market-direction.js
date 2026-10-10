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
         close<=0||high<Math.max(open,close,low)||low>Math.min(open,close)||
         start+minutes*60000>now-1500)continue;
      candles.set(start,{start,open,high,low,close});
    }
    const completed=[...candles.values()].sort((a,b)=>a.start-b.start);
    if(completed.length<6)throw new Error('Недостатньо завершених свічок для порівняння.');
    const recent=completed.slice(-6),first=recent[0],last=recent[5];
    const step=minutes*60000;
    if(recent.some((row,i)=>i>0 && row.start-recent[i-1].start!==step))
      throw new Error('В останніх шести свічках є пропуски. Напрям не визначено.');
    // A gap inside the backtest would compare non-adjacent candles and overstate
    // performance. Return a neutral scenario rather than a fabricated hit rate.
    const scenarioHistory=completed.slice(-65);
    const hasGaps=scenarioHistory.some((row,i)=>i>0 && row.start-scenarioHistory[i-1].start!==step);
    // We do not substitute old market history for the user's current chart.
    const age=now-(last.start+minutes*60000);
    if(age>minutes*60000*3)
      throw new Error('Дані Bybit застарілі. Онови пізніше.');
    const delta=100*(last.close/first.close-1);
    const direction=Math.abs(delta)<.005?'unknown':delta>0?'up':'down';
    return {symbol,category,intervalMinutes:minutes,completedCount:completed.length,
      direction,changePct:delta,
      scenario:hasGaps?
        {bias:'unknown',score:0,reasons:[],trials:0,hits:0,misses:0,skipped:0,observedAccuracy:null}:
        evaluate(completed),
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
    const heading=create('h3','margin:0 0 6px','📊 Актуальний ринок: факт і гіпотеза');
    const info=create('p','font-size:13px;line-height:1.55;margin:0 0 12px',
      'Для оцінки наступних 5 хв обери правильну пару, тип ринку й свічку. Початковий вибір BTCUSDT · ф’ючерси · 5 хв — ПЕРЕВІР, чи він відповідає фото. Висновок на фото нижче означає лише минулий рух; OTC та інші біржі мають інші ціни.');
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
    category.value='linear';
    field('Тип ринку',category);
    const timeframe=document.createElement('select');
    for(const [value,label] of [['1','1 хв'],['5','5 хв'],['15','15 хв'],['30','30 хв'],['60','1 год'],['240','4 год']]){
      const option=document.createElement('option');option.value=value;option.textContent=label;timeframe.appendChild(option);
    }
    timeframe.value='5';field('Свічка',timeframe);
    const button=create('button','','🔎 Оцінити наступну свічку (гіпотеза)');
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
      const s=answer.scenario;
      const time=new Date(answer.lastClosedAt).toLocaleString('uk-UA');
      const headline=create('div','font-size:12px;font-weight:750;letter-spacing:.03em;margin:8px 0',
        'МИНУЛИЙ РУХ: ОСТАННІ П’ЯТЬ ЗАВЕРШЕНИХ СВІЧОК');
      const historyLabels={up:'↑ Ріст',down:'↓ Спад',unknown:'— Майже без змін'};
      const prior=create('div','font-size:clamp(21px,3.5vw,29px);font-weight:700;margin:4px 0',
        historyLabels[answer.direction]);
      const historic=create('p','font-size:12px;line-height:1.65;white-space:pre-wrap;margin:8px 0 14px',
        answer.symbol+' · '+(answer.category==='spot'?'Spot':'Linear')+' · '+answer.intervalMinutes+' хв\n'+
        'За попередні п’ять свічок: '+percent(answer.changePct)+'\n'+
        'Ціна: '+formatPrice(answer.firstClose)+' → '+formatPrice(answer.lastClose)+' USDT\n'+
        'Останнє закриття: '+time);
      const forecast=create('section','border:1px solid #8996aa;border-radius:12px;padding:14px;margin:12px 0;background:rgba(100,116,139,.06)');
      const title=create('div','font-size:12px;font-weight:750;letter-spacing:.03em',
        'НАСТУПНІ '+answer.intervalMinutes+' ХВ · ГІПОТЕЗА, НЕ СИГНАЛ');
      const label=s.bias==='up'?'↑ ВИСХІДНИЙ НАХИЛ':
        s.bias==='down'?'↓ СПАДНИЙ НАХИЛ':'— НЕВИЗНАЧЕНО';
      const big=create('div','font-size:clamp(23px,4vw,33px);font-weight:800;line-height:1.28;margin:9px 0',
        label);
      big.style.color=s.bias==='up'?'#36ce96':s.bias==='down'?'#f87171':'inherit';
      const notice=create('p','font-size:12px;line-height:1.6;margin:7px 0',
        'Це лише узгодженість EMA, RSI, імпульсу й останнього тіла свічки. '+
        'Напрям наступної свічки невідомий; результат не є обчисленою ймовірністю.');
      const testMessage=s.trials>=25?
        ('Історична перевірка: '+s.hits+' із '+s.trials+' випадків ('+
         s.observedAccuracy.toFixed(1)+'%). Це малий ретроспективний тест без гарантії повторення.') :
        ('Історична перевірка: лише '+s.trials+
         ' випадків; замало для оцінки результативності.');
      const test=create('p','font-size:12px;line-height:1.6;margin:7px 0',testMessage);
      const details=document.createElement('details');
      const summary=create('summary','','Як сформувалася гіпотеза');
      const explanation=create('p','font-size:12px;white-space:pre-wrap;line-height:1.6',
        s.reasons.length?s.reasons.join('\n'):'Недостатньо завершених свічок.');
      details.append(summary,explanation);
      const caution=create('p','font-size:12px;line-height:1.6;margin:9px 0',
        'Джерело: публічні закриті свічки Bybit V5, не завантажене фото. '+
        'Якщо фото старе або з OTC/іншої біржі, порівнювати напрями некоректно. Ордери не відкриваються.');
      forecast.append(title,big,notice,test,details,caution);
      result.append(forecast,headline,prior,historic);
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
        status.textContent='✅ Отримано завершені свічки Bybit. Гіпотеза не є торговим сигналом.';
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