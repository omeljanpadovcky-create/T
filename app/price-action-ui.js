/* Crypto Myshka live OHLC research for the first three trading videos.
 * Data source is Bybit public V5 (NOT Pocket Option OTC, NOT an uploaded image).
 * This is browser-only, read-only, no keys, no orders, no Martingale.
 */
(() => {
  'use strict';
  const engine=window.cryptoMyshkaPriceAction;
  const root=document.getElementById('price-action-live');
  if(!root||!engine)return;
  const $=id=>document.getElementById(id);
  const status=$('pa-status'),output=$('pa-output'),button=$('pa-run');
  const symbolInput=$('pa-symbol'),payoutInput=$('pa-payout');
  const format=n=>Number.isFinite(n)?n.toLocaleString('uk-UA',{maximumFractionDigits:6}):'—';
  let active=false,current=null,seq=0;
  function node(tag,content,cls){
    const n=document.createElement(tag);
    if(cls)n.className=cls;
    if(content!==undefined)n.textContent=String(content);
    return n;
  }
  function card(title,value,sub){
    const el=node('div',undefined,'pa-metric');
    el.append(node('small',title),node('strong',value),node('small',sub));
    return el;
  }
  function render(summary,context,history,symbol,payout,count,latestTime){
    output.replaceChildren();
    const big=node('div',undefined,'pa-verdict');
    let verdict=summary.bias;
    if(verdict!=='wait'&&context.trend!=='sideways'&&context.trend!==verdict)
      verdict='wait';
    big.classList.add(verdict==='up'?'pa-up':verdict==='down'?'pa-down':'pa-wait');
    big.textContent=verdict==='up'?'↑ UP · дослідницький сценарій':
      verdict==='down'?'↓ DOWN · дослідницький сценарій':'— WAIT · умов недостатньо';
    const intro=node('p',symbol+' · Bybit V5 · M1 · завершено: '+
      new Date(latestTime).toLocaleString('uk-UA')+' · останнє закриття '+
      format(summary.lastClose)+' USDT','pa-note');
    output.append(big,intro);
    const metrics=node('div',undefined,'pa-metrics');
    const trend=t=>t==='up'?'Висхідний (HH/HL)':t==='down'?'Спадний (LH/LL)':'Непідтверджений / боковик';
    const support=summary.levels?.support;
    const resistance=summary.levels?.resistance;
    metrics.append(
      card('M1 · структура',trend(summary.trend),'За підтвердженими локальними вершинами'),
      card('M5 · ширший тренд',trend(context.trend),'Не використовувати M1 проти чіткого M5'),
      card('Підтримка',support?format(support.price):'—',
        support?support.touches+' підтверджених торкань':'Повторні мінімуми не підтверджені'),
      card('Опір',resistance?format(resistance.price):'—',
        resistance?resistance.touches+' підтверджених торкань':'Повторні максимуми не підтверджені'),
      card('Формація M1',summary.pattern?.name||'—','Знайдена формація не гарантує пробою'),
      card('Вибірка M1',String(count)+' завершених свічок','Жодної незакритої свічки або підміни OTC'));
    output.append(metrics);
    const reasons=node('div',undefined,'pa-reasons');
    reasons.append(node('h3','Чому таке рішення'));
    const list=node('ul');
    summary.reasons.forEach(x=>list.append(node('li',x)));
    if(summary.bias!==verdict)
      list.append(node('li','Протиріччя: напрям M1 не підтверджується структурою M5. Підсумок WAIT.'));
    reasons.append(list);output.append(reasons);
    const stats=node('div',undefined,'pa-backtest');
    stats.append(node('h3','Історичний M1 + M5 walk-forward тест'));
    const evaluation=history.trades>=30?
      history.wins+' / '+history.trades+' правильних ('+history.accuracy.toFixed(1)+'%)':
      'Лише '+history.trades+' перевірених входів. Для оцінки точності потрібно щонайменше 30.';
    stats.append(node('p',evaluation));
    const net=history.netUnits>=0?'+':'';
    stats.append(node('p','Сценаріїв WAIT: '+history.wait+
      ' · втрат: '+history.losses+' · нічиїх: '+history.ties+
      ' · найбільша серія мінусів: '+history.maxLossStreak));
    stats.append(node('p','Модель фіксованої ставки 1 одиниця, виплата '+
      Math.round(payout*100)+'%: '+net+history.netUnits.toFixed(2)+
      ' од. (не реальні гроші).'));
    stats.append(node('p','Перевірка: для кожного історичного моменту модель бачить тільки попередні завершені свічки; результат — наступна завершена M1. '+
      'Кожен історичний вхід фільтрується останньою на той момент завершеною M5. Комісії, затримки та різниця котирувань не враховані.','pa-note'));
    output.append(stats);
    output.append(node('p',
      '⚠️ Біржові котирування Bybit НЕ тотожні Pocket Option OTC. Якщо фото з OTC, значення рівнів тут не можна переносити на нього. '+
      'Це дослідницький технічний аналіз, не AI, не гарантія наступної хвилини та не торговий сигнал.','pa-note'));
  }
  function parse(payload,symbol,minutes,now=Date.now()){
    if(payload?.retCode!==0||!Array.isArray(payload?.result?.list))
      throw Error('Bybit не повернув список свічок.');
    if(payload.result.symbol&&payload.result.symbol!==symbol)
      throw Error('Біржа повернула інший символ.');
    if(payload.result.category&&payload.result.category!=='linear')
      throw Error('Біржа повернула інший тип ринку.');
    const interval=minutes*60000,all=new Map();
    for(const row of payload.result.list){
      if(!Array.isArray(row))continue;
      const c={start:Number(row[0]),open:Number(row[1]),high:Number(row[2]),
        low:Number(row[3]),close:Number(row[4])};
      if(!Object.values(c).every(Number.isFinite)||c.start<=0||c.low<=0||
         c.low>Math.min(c.open,c.close)||c.high<Math.max(c.open,c.close,c.low)||
         c.start+interval>now-1500)continue;
      all.set(c.start,c);
    }
    const sorted=[...all.values()].sort((a,b)=>a.start-b.start);
    if(!sorted.length)throw Error('Немає підтверджених закритих свічок.');
    const latest=sorted[sorted.length-1];
    if(now-(latest.start+interval)>interval*3)
      throw Error('Свічки застаріли. Аналіз не показує старі дані як поточні.');
    // Keep only the contiguous tail: crossing a data gap distorts a walk-forward backtest.
    let cut=sorted.length-1;
    while(cut>0&&sorted[cut].start-sorted[cut-1].start===interval)cut--;
    const rows=sorted.slice(cut);
    if(rows.length<100)throw Error('Менше 100 послідовних завершених свічок. Відмовляємося від статистики.');
    return rows;
  }
  async function json(url,controller){
    const res=await fetch(url,{cache:'no-store',signal:controller.signal,
      headers:{Accept:'application/json'}});
    if(!res.ok)throw Error('HTTP '+res.status+' від Bybit');
    return res.json();
  }
  async function run(){
    if(active)return;
    const symbol=String(symbolInput.value||'').toUpperCase().replace(/[\s/]/g,'');
    const payout=Number(payoutInput.value)/100;
    if(!/^[A-Z0-9]{5,22}$/.test(symbol)||!symbol.endsWith('USDT')){
      status.textContent='Потрібна біржова пара, наприклад BTCUSDT.';return;
    }
    if(!(payout>=.5&&payout<=1)){
      status.textContent='Введи гіпотетичну виплату 50–100%.';return;
    }
    active=true;button.disabled=true;
    if(current)current.abort();
    const controller=new AbortController();current=controller;
    const token=++seq;
    const timeout=setTimeout(()=>controller.abort(),14000);
    status.textContent='Читаємо M1 та M5 '+symbol+' з Bybit V5…';
    try{
      const host='https://api.bybit.com/v5/market/kline?category=linear&symbol='+
        encodeURIComponent(symbol);
      const [m1,m5]=await Promise.all([
        json(host+'&interval=1&limit=700',controller),
        json(host+'&interval=5&limit=200',controller)
      ]);
      const now=Date.now(),one=parse(m1,symbol,1,now),five=parse(m5,symbol,5,now);
      const summary=engine.analyze(one);
      const context=engine.analyze(five);
      const history=engine.backtestMulti(one,five,{payout});
      if(token!==seq)return;
      render(summary,context,history,symbol,payout,one.length,one[one.length-1].start+60000);
      status.textContent='✓ Перевірено '+one.length+' завершених M1 і '+
        five.length+' M5 свічок. Оновлення лише поки сторінка відкрита.';
    }catch(e){
      if(token===seq){
        output.replaceChildren();
        output.append(node('p','Немає перевіреного ринкового результату: '+
          String(e?.name==='AbortError'?'перевищено час запиту':e?.message||'невідома помилка')+
          '. Немає підміни ринку вигаданими даними.','pa-note'));
        status.textContent='⚠️ Дані не підтверджено.';
      }
    }finally{
      clearTimeout(timeout);
      if(current===controller)current=null;
      active=false;button.disabled=false;
    }
  }
  button.addEventListener('click',run);
  symbolInput.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();run();}});
  // Autonomous refresh only while the page is open, not a fake 24/7 server.
  const ticker=setInterval(()=>{if(!document.hidden)run();},60000);
  window.addEventListener('pagehide',()=>{clearInterval(ticker);current?.abort();},{once:true});
  run();
})();
