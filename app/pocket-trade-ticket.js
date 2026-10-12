/* Pocket-like BUY/SELL virtual ticket. No broker calls, no real money, no auto-fill. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const KEY = 'crypto-myshka-pocket-paper-v1';
  const LIMIT = 300;
  const fmt = amount => Number(amount).toLocaleString('uk-UA',
    {minimumFractionDigits:2,maximumFractionDigits:2});
  const elapsed = expiry => {
    const sec=Math.max(0,Math.ceil((Date.parse(expiry)-Date.now())/1000));
    return [Math.floor(sec/3600),Math.floor(sec%3600/60),sec%60]
      .map(x=>String(x).padStart(2,'0')).join(':');
  };
  const read = () => {
    try {
      const value=JSON.parse(localStorage.getItem(KEY)||'[]');
      return Array.isArray(value)?value.filter(x=>x&&typeof x.id==='string').slice(0,LIMIT):[];
    }catch{return [];}
  };
  const prefs = () => window.cryptoMyshkaPocket?.getPrefs?.() || null;
  const valid = p => p && /^[A-Za-z0-9 /._-]{3,50}$/.test(p.pair) &&
    [30,60,180,300].includes(p.expiry) &&
    Number.isFinite(p.stake)&&p.stake>=.01&&p.stake<=100000 &&
    Number.isFinite(p.payout)&&p.payout>0&&p.payout<=100;
  function refresh(){
    const p=prefs();if(!p)return;
    $('ticket-pair').textContent=p.pair||'Вибери пару';
    if(document.activeElement!==$('ticket-expiry'))$('ticket-expiry').value=String(p.expiry);
    if(document.activeElement!==$('ticket-stake'))
      $('ticket-stake').value=Number.isFinite(p.stake)?String(p.stake):'';
    $('ticket-payout-pct').textContent=Number.isFinite(p.payout)?'+'+fmt(p.payout)+'%':'—';
    $('ticket-payout-profit').textContent=valid(p)?
      'Прибуток за WIN: +'+fmt(p.stake*p.payout/100)+' $':'Перевір суму й виплату';
    const state=window.cryptoMyshkaPocket?.getAnalysisState?.()||{};
    const guide=$('ticket-guide-action'),guideNote=$('ticket-guide-note');
    if(guide&&guideNote){
      if(state.loading){
        guide.textContent='⏳ JEV аналізує фото…';
        guide.disabled=true;
        guideNote.textContent='Дослідницька оцінка обробляється, BUY / SELL ще не підтверджені.';
      }else if(!state.hasImage){
        guide.textContent='📷 Додати фото графіка';
        guide.disabled=false;
        guideNote.textContent=state.cloudReady?
          '✅ API доступний. Для оцінки UP / DOWN / STOP потрібен свіжий скриншот.':
          'Перший крок — додай фото, далі підключи хмарний JEV.';
      }else if(state.lastErrorCode==='PROVIDER_CREDITS'){
        guide.textContent='🔬 Сканувати локально · без оплати';
        guide.disabled=false;
        guideNote.textContent='APInex HTTP 402: хмарний аналіз заблоковано. '+
          'Локальний сканер безкоштовно описує вже намальовані свічки, але НЕ прогнозує експірацію.';
      }else if(state.lastError){
        guide.textContent=state.cloudReady?'↻ Повторити аналіз фото':'🔑 Перевірити підключення JEV';
        guide.disabled=false;
        guideNote.textContent='⚠️ '+(state.lastErrorCode?'['+state.lastErrorCode+'] ':'')+
          state.lastError.slice(0,240);
      }else if(!state.cloudReady){
        guide.textContent='🔑 Перевірити підключення JEV';
        guide.disabled=false;
        guideNote.textContent='Фото вже є. Підключи API, щоб перевірити графік.';
      }else if(!state.hasHypothesis){
        guide.textContent='🔬 Аналізувати фото JEV';
        guide.disabled=false;
        guideNote.textContent='Скріншот завантажено. Запусти AI — фото не аналізується автоматично.';
      }else{
        guide.textContent='📷 Завантажити нове фото';
        guide.disabled=false;
        guideNote.textContent='Оцінка лише за попереднім фото. Новий графік потрібний для наступної перевірки.';
      }
    }
    const offline=$('ticket-offline-result');
    if(offline){
      const local=state.localReport;
      if(local){
        offline.hidden=false;
        const label=local.reliable?
          local.direction==='up'?'↑ Раніше свічки рухалися вгору':
          local.direction==='down'?'↓ Раніше свічки рухалися вниз':
          'Раніший напрям невизначений':'Розпізнавання графіка ненадійне';
        offline.textContent='🔎 ЛОКАЛЬНИЙ СКАНЕР · МИНУЛІ СВІЧКИ · БЕЗ AI/КВОТИ. '+label+
          ' · Знайдено '+(local.candidates||0)+' елементів. '+
          'Не дає BUY/SELL на майбутню свічку.';
      }else{
        offline.hidden=true;offline.textContent='';
      }
    }
    const insight=window.cryptoMyshkaPocket?.getScreenshotHypothesis?.()||null;
    const issuedAt=Date.parse(insight?.created||'');
    const freshnessMs=Math.min(60000,Math.max(10000,Number(insight?.expiry||60)*1000));
    const ageMs=Date.now()-issuedAt;
    const fresh=Boolean(insight&&['UP','DOWN'].includes(insight.direction)&&
      insight.source==='pocket_cloud_screenshot'&&
      insight.broker_verified===false&&insight.signal_validated===false&&
      Number.isFinite(issuedAt)&&ageMs>=0&&ageMs<freshnessMs);
    const records=read().filter(x=>x.source==='pocket_manual_demo');
    const active=records.find(x=>x.outcome==='pending'&&Date.parse(x.expiresAt)>Date.now());
    const last=records[0];
    $('ticket-buy').disabled=$('ticket-sell').disabled=!valid(p)||Boolean(active);
    const pulseBuy=fresh&&insight.direction==='UP'&&!$('ticket-buy').disabled;
    const pulseSell=fresh&&insight.direction==='DOWN'&&!$('ticket-sell').disabled;
    $('ticket-buy').classList.toggle('jev-flash',pulseBuy);
    $('ticket-sell').classList.toggle('jev-flash',pulseSell);
    $('ticket-buy').classList.toggle('jev-idle',pulseSell);
    $('ticket-sell').classList.toggle('jev-idle',pulseBuy);
    $('ticket-buy').setAttribute('aria-description',pulseBuy?
      'Пульсує за дослідницькою гіпотезою JEV; лише демоугода, прогноз не перевірений.':'Віртуальна ручна угода, без реального ордера.');
    $('ticket-sell').setAttribute('aria-description',pulseSell?
      'Пульсує за дослідницькою гіпотезою JEV; лише демоугода, прогноз не перевірений.':'Віртуальна ручна угода, без реального ордера.');
    const caption=$('ticket-jev-hint');
    if(active){
      $('ticket-jev-direction').textContent='⏸ Є активна демоугода';
      caption.textContent='Підсвічування призупинене до завершення віртуальної угоди.';
    }else if(pulseBuy||pulseSell){
      $('ticket-jev-direction').textContent=pulseBuy?'↑ BUY · гіпотеза JEV':'↓ SELL · гіпотеза JEV';
      caption.textContent='⚡ Візуальна підказка лише для демо · оцінка зі скриншота, не сигнал брокера · ще '+Math.ceil((freshnessMs-ageMs)/1000)+' с';
    }else if(state.lastError){
      $('ticket-jev-direction').textContent='⚠️ Помилка аналізу JEV';
      caption.textContent=(state.lastErrorCode?'['+state.lastErrorCode+'] ':'')+
        state.lastError.slice(0,240);
    }else if(insight?.direction==='STOP'){
      $('ticket-jev-direction').textContent='⏸ СТОП · JEV утримався';
      caption.textContent='AI не підтримав напрям. Жодних кнопок із сигналом.';
    }else if(insight&&['UP','DOWN'].includes(insight.direction)){
      $('ticket-jev-direction').textContent='⌛ Гіпотеза застаріла';
      caption.textContent='Зроби нове фото та запусти JEV знову. Старий прогноз не підсвічується.';
    }else{
      $('ticket-jev-direction').textContent='⏳ Немає оцінки JEV';
      caption.textContent='Додай фото й отримай відповідь хмарного JEV, щоб увімкнути підсвічування.';
    }
    if(active){
      $('ticket-countdown').textContent=elapsed(active.expiresAt);
      $('ticket-order-status').textContent=(active.direction==='UP'?'↗ BUY':'↘ SELL')+
        ' · '+active.pair+' · '+fmt(active.stake)+' $ · чекаємо експірації. Це лише демозапис.';
    }else if(last?.outcome==='pending'){
      $('ticket-countdown').textContent='00:00:00';
      $('ticket-order-status').textContent='Час демоугоди минув. Звір котирування на Pocket Option і вручну постав WIN / LOSS / TIE у журналі.';
    }else if(last){
      $('ticket-countdown').textContent='—';
      const result={hit:'WIN',miss:'LOSS',tie:'TIE',void:'скасовано'}[last.outcome]||'невідомо';
      $('ticket-order-status').textContent='Остання DEMO: '+(last.direction==='UP'?'BUY':'SELL')+' · '+result+'.';
    }else{
      $('ticket-countdown').textContent='—';
      $('ticket-order-status').textContent=valid(p)?
        'BUY або SELL відкриває лише віртуальну угоду в журналі.':
        'Перевір пару, час, суму й виплату.';
    }
  }
  function record(direction){
    const p=prefs();
    if(!valid(p)){refresh();$('ticket-order-status').textContent='⚠️ Некоректні параметри демоугоди.';return;}
    const rows=read();
    if(rows.some(x=>x.source==='pocket_manual_demo'&&x.outcome==='pending'&&
      Date.parse(x.expiresAt)>Date.now())){refresh();return;}
    const now=Date.now();
    const id=typeof crypto!=='undefined'&&crypto.randomUUID?crypto.randomUUID():
      now+'-'+Math.random().toString(36).slice(2);
    rows.unshift({
      id,created:new Date(now).toISOString(),expiresAt:new Date(now+p.expiry*1000).toISOString(),
      pair:p.pair,timeframe:p.timeframe,expiry:p.expiry,payout:p.payout,stake:p.stake,direction,
      source:'pocket_manual_demo',mode:'paper_only',provider:'manual_user',
      outcome:'pending',manuallyReported:true,broker_verified:false,
      quotes_verified:false,signal_validated:false,
      reason:'Ручна DEMO-кнопка '+(direction==='UP'?'BUY':'SELL')+
        ' у Crypto Myshka. Реальну угоду Pocket Option не відкрито.',
      risk:'Результат не відомий автоматично; його потрібно вручну перевірити після експірації.'
    });
    try{localStorage.setItem(KEY,JSON.stringify(rows.slice(0,LIMIT)));}
    catch{$('ticket-order-status').textContent='⚠️ Не вдалося зберегти демоугоду.';return;}
    refresh();
  }
  function init(){
    if(!$('ticket-buy')||!window.cryptoMyshkaPocket)return;
    $('ticket-buy').addEventListener('click',()=>record('UP'));
    $('ticket-sell').addEventListener('click',()=>record('DOWN'));
    $('ticket-guide-action')?.addEventListener('click',()=>{
      const current=window.cryptoMyshkaPocket?.getAnalysisState?.()||{};
      if(current.loading)return;
      if(current.lastErrorCode==='PROVIDER_CREDITS'&&current.hasImage){
        $('scan-pixels')?.click();
        $('scan-output')?.scrollIntoView?.({behavior:'smooth',block:'nearest'});
      }else if(!current.hasImage||current.hasHypothesis){
        $('pocket-photo')?.click();
      }else if(!current.cloudReady){
        $('pocket-ai-card')?.scrollIntoView?.({behavior:'smooth',block:'start'});
        $('cloud-access')?.focus();
      }else{
        $('pocket-ai-card')?.scrollIntoView?.({behavior:'smooth',block:'start'});
        $('run-pocket-ai')?.click();
      }
    });
    $('ticket-expiry').addEventListener('change',()=>{
      $('pocket-expiry').value=$('ticket-expiry').value;
      $('pocket-expiry').dispatchEvent(new Event('input',{bubbles:true}));
      refresh();
    });
    $('ticket-stake').addEventListener('input',()=>{
      $('pocket-stake').value=$('ticket-stake').value;
      $('pocket-stake').dispatchEvent(new Event('input',{bubbles:true}));
      refresh();
    });
    ['pocket-pair','custom-pair','pocket-expiry','pocket-payout','pocket-stake']
      .forEach(id=>$(id)?.addEventListener('input',refresh));
    window.addEventListener('storage',refresh);
    window.addEventListener('crypto-myshka-jev-verdict-change',refresh);
    window.addEventListener('crypto-myshka-analysis-state-change',refresh);
    refresh();
    setInterval(()=>{if(!$('screen-analysis').hidden)refresh();},1000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();