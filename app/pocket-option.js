/* Crypto Myshka Pocket Option screenshot lab. No broker API, no real orders.
 * Screenshots/credentials are never stored in GitHub. Only cropped chart pixels
 * are transmitted after clicking the AI button, with a session-only access code.
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const JOURNAL_KEY='crypto-myshka-pocket-paper-v1';
  const CLOUD_SESSION_KEY='jev-pocket-cloud-tab-v1';
  const SCREENS=new Set(['home','analysis','history','archive','autodemo']);
  const LIMIT=300;
  const state={image:null,filename:'',crop:null,canvasWidth:0,canvasHeight:0,
    dragStart:null,dragging:false,ai:null,cloudReady:false,model:'',provider:'',loading:false};
  const fmt=(n,d=2)=>Number.isFinite(Number(n))?Number(n).toLocaleString('uk-UA',{minimumFractionDigits:d,maximumFractionDigits:d}):'—';
  const localJournal=()=>{
    try {
      const rows=JSON.parse(localStorage.getItem(JOURNAL_KEY)||'[]');
      return Array.isArray(rows)?rows.filter(r=>r&&typeof r.id==='string'&&['UP','DOWN','STOP'].includes(r.direction)).slice(0,LIMIT):[];
    }catch{return [];}
  };
  const saveJournal=rows=>{try{localStorage.setItem(JOURNAL_KEY,JSON.stringify(rows.slice(0,LIMIT)));return true;}catch{return false;}};
  function toast(message){const node=$('toast');node.textContent=message;node.hidden=false;clearTimeout(toast.t);toast.t=setTimeout(()=>node.hidden=true,3500);}
  function route(view){
    if(!SCREENS.has(view))view='home';
    document.querySelectorAll('[data-screen]').forEach(el=>el.hidden=el.dataset.screen!==view);
    document.querySelectorAll('button[data-go]').forEach(btn=>{
      btn.classList.toggle('active',btn.dataset.go===view);
      if(btn.dataset.go===view)btn.setAttribute('aria-current','page');else btn.removeAttribute('aria-current');
    });
    if(location.hash!=='#'+view)history.replaceState(null,'','#'+view);
    if(view==='home')renderHome();
    if(view==='history')renderJournal();
    window.scrollTo({top:0,behavior:'instant'});
  }
  function activePair(){
    const chosen=$('pocket-pair').value;
    return chosen==='custom'?$('custom-pair').value.trim().slice(0,50):chosen;
  }
  function pairValid(p){return /^[A-Za-z0-9 /._-]{3,50}$/.test(p);}
  function getPrefs(){
    return {pair:activePair(),timeframe:Number($('pocket-timeframe').value),
      expiry:Number($('pocket-expiry').value),payout:Number($('pocket-payout').value),
      stake:Number($('pocket-stake').value)};
  }
  function showMath(){
    const p=getPrefs();const q=p.payout/100;
    const valid=Number.isFinite(p.payout)&&p.payout>0&&p.payout<=100&&
      Number.isFinite(p.stake)&&p.stake>0&&p.stake<=100000;
    const values=valid?[
      ['Потрібна частка влучань',fmt(100/(1+q),2)+' %','warn'],
      ['Вдала демоспроба', '+'+fmt(p.stake*q)+' $','positive'],
      ['Невдала демоспроба','−'+fmt(p.stake)+' $','negative'],
      ['Час оцінки',p.expiry+' с','']
    ]:[['Параметри','Уведи виплату 1–100% і позитивну суму','warn']];
    const box=$('pocket-math');box.replaceChildren();
    values.forEach(([label,value,cls])=>{
      const cell=document.createElement('div');cell.className='metric '+cls;
      const sm=document.createElement('small');sm.textContent=label;
      const strong=document.createElement('strong');strong.textContent=value;
      cell.append(sm,strong);box.append(cell);
    });
    if(state.ai && (state.ai.expiry!==p.expiry||state.ai.timeframe!==p.timeframe||
       state.ai.pair!==p.pair)){
      state.ai=null;renderVerdict(null,'Параметри змінилися. Для нової експірації повтори AI-аналіз.');
    }
  }
  function renderHome(){
    const rows=localJournal().filter(x=>x.source!=='pocket_manual_demo'),done=rows.filter(x=>x.outcome==='hit'||x.outcome==='miss');
    $('home-total').textContent=String(rows.length);
    $('home-checked').textContent=String(done.length);
    const last=rows[0];$('home-last').textContent=last?(last.direction==='UP'?'↑':last.direction==='DOWN'?'↓':'⏸')+' '+last.pair:'—';
  }
  function renderVerdict(answer,notice){
    const heading=$('ai-direction'),reason=$('ai-reason'),risk=$('ai-risk'),meta=$('ai-meta');
    const direction=answer&&['UP','DOWN'].includes(answer.direction)?answer.direction:'STOP';
    heading.textContent=direction==='UP'?'↑ ВГОРУ · гіпотеза':direction==='DOWN'?'↓ ВНИЗ · гіпотеза':'⏸ СТОП';
    heading.className=direction==='UP'?'up':direction==='DOWN'?'down':'stop';
    reason.textContent=answer?.reason||notice||'Без перевіреної відповіді AI не робимо висновків про наступний рух.';
    risk.textContent=answer?.risk?'Ризик: '+answer.risk:'';
    meta.textContent=answer?'Джерело: тільки обраний скріншот · '+(answer.provider||'AI')+
      ' · горизонт '+answer.expiry+' с · OTC-котирування незалежно не перевірені · результат НЕ гарантується.':'';
    $('save-paper').disabled=!state.ai;
  }
  function imageStatus(text){$('image-info').textContent=text;}
  function resetScan(text){
    $('scan-output').textContent=text||'Локальний сканер описує минулі свічки. Жодних прогнозів без перевіреної відповіді JEV.';
    state.ai=null;renderVerdict(null);
    updateAIButton();
  }
  function drawCanvas(){
    const cv=$('pocket-canvas'),image=state.image;if(!image)return;
    const ctx=cv.getContext('2d');
    const w=cv.width,h=cv.height;ctx.clearRect(0,0,w,h);ctx.drawImage(image,0,0,w,h);
    const b=state.crop;if(!b)return;
    ctx.fillStyle='rgba(0,0,0,.48)';
    ctx.fillRect(0,0,w,b.y);ctx.fillRect(0,b.y,b.x,b.h);
    ctx.fillRect(b.x+b.w,b.y,w-b.x-b.w,b.h);ctx.fillRect(0,b.y+b.h,w,h-b.y-b.h);
    ctx.strokeStyle='#fbd36c';ctx.lineWidth=2;ctx.setLineDash([9,5]);
    ctx.strokeRect(b.x+1,b.y+1,Math.max(1,b.w-2),Math.max(1,b.h-2));ctx.setLineDash([]);
  }
  function cropFallback(){
    const w=state.canvasWidth,h=state.canvasHeight;
    return {x:Math.round(w*.12),y:Math.round(h*.14),w:Math.round(w*.62),h:Math.round(h*.67)};
  }
  function pickAutoCrop(){
    const cv=$('pocket-canvas');if(!state.image)return;
    const ctx=cv.getContext('2d',{willReadFrequently:true});
    // Always inspect ORIGINAL pixels. On the initial upload canvas is blank,
    // and later drawing overlays may otherwise be mistaken for candles.
    ctx.clearRect(0,0,cv.width,cv.height);
    ctx.drawImage(state.image,0,0,cv.width,cv.height);
    const original=ctx.getImageData(0,0,cv.width,cv.height);
    const candidate=window.cryptoMyshkaPhotoScan?.findChartBounds?.(original);
    state.crop=candidate||cropFallback();drawCanvas();
    imageStatus((candidate?'Автоматично знайдено можливе поле свічок.':'Точну область не знайдено: задано орієнтовну рамку.')+
      ' Перетягни рамку вручну, щоб прибрати меню, баланс та індикатори, які заважають аналізу.');
    resetScan('Область виділена. Натисни «Описати минулий рух» для локального сканера.');
  }
  async function loadImage(file){
    if(!file||!['image/png','image/jpeg','image/webp'].includes(file.type)||file.size<1||file.size>8*1024*1024){
      toast('Потрібен JPG, PNG або WebP до 8 МБ.');return;
    }
    const reader=new FileReader();
    reader.onerror=()=>toast('Не вдалося прочитати фото.');
    reader.onload=()=>{
      const img=new Image();
      img.onerror=()=>toast('Не вдалося відкрити файл як зображення.');
      img.onload=()=>{
        if(img.naturalWidth<140||img.naturalHeight<110||img.naturalWidth*img.naturalHeight>15000000){
          toast('Зображення надто мале або велике для аналізу.');return;
        }
        state.image=img;state.filename=file.name||'clipboard.png';state.ai=null;
        const scale=Math.min(1,980/img.naturalWidth,620/img.naturalHeight);
        const cv=$('pocket-canvas');
        cv.width=Math.round(img.naturalWidth*scale);cv.height=Math.round(img.naturalHeight*scale);
        state.canvasWidth=cv.width;state.canvasHeight=cv.height;
        $('empty-photo').hidden=true;$('photo-stage').hidden=false;
        pickAutoCrop();imageStatus(state.filename+' · '+img.naturalWidth+' × '+img.naturalHeight+
          ' · Обведи лише свічковий графік. Потім натисни JEV.');
        updateAIButton();toast('Фото завантажено. Обери область свічок.');
      };img.src=String(reader.result);
    };reader.readAsDataURL(file);
  }
  function point(event){
    const rect=$('pocket-canvas').getBoundingClientRect();
    return {x:Math.max(0,Math.min(state.canvasWidth,(event.clientX-rect.left)*state.canvasWidth/rect.width)),
      y:Math.max(0,Math.min(state.canvasHeight,(event.clientY-rect.top)*state.canvasHeight/rect.height))};
  }
  function installPointer(){
    const cv=$('pocket-canvas');
    cv.addEventListener('pointerdown',e=>{
      if(!state.image)return;
      e.preventDefault();state.dragStart=point(e);state.dragging=true;
      cv.setPointerCapture(e.pointerId);
    });
    cv.addEventListener('pointermove',e=>{
      if(!state.dragging||!state.dragStart)return;
      const p=point(e),a=state.dragStart;
      state.crop={x:Math.round(Math.min(a.x,p.x)),y:Math.round(Math.min(a.y,p.y)),
        w:Math.round(Math.abs(p.x-a.x)),h:Math.round(Math.abs(p.y-a.y))};
      drawCanvas();
    });
    function release(e){
      if(!state.dragging)return;
      state.dragging=false;state.dragStart=null;
      if(state.crop.w<60||state.crop.h<60){state.crop=cropFallback();}
      drawCanvas();resetScan('Нову область обрано. Скануй пікселі або відправ її до хмарного JEV.');
    }
    cv.addEventListener('pointerup',release);
    cv.addEventListener('pointercancel',release);
  }
  function croppedCanvas(){
    if(!state.image||!state.crop||state.crop.w<60||state.crop.h<60)throw Error('Обери достатньо велику область графіка.');
    const b=state.crop,img=state.image;
    const x=Math.floor(b.x/state.canvasWidth*img.naturalWidth);
    const y=Math.floor(b.y/state.canvasHeight*img.naturalHeight);
    const w=Math.min(img.naturalWidth-x,Math.ceil(b.w/state.canvasWidth*img.naturalWidth));
    const h=Math.min(img.naturalHeight-y,Math.ceil(b.h/state.canvasHeight*img.naturalHeight));
    const scale=Math.min(1,1200/w,900/h);
    const cv=document.createElement('canvas');
    cv.width=Math.max(1,Math.round(w*scale));cv.height=Math.max(1,Math.round(h*scale));
    cv.getContext('2d').drawImage(img,x,y,w,h,0,0,cv.width,cv.height);
    return cv;
  }
  function scanPixels(){
    try{
      const cv=croppedCanvas(),result=window.cryptoMyshkaPhotoScan?.analyzePixels?.(
        cv.getContext('2d',{willReadFrequently:true}).getImageData(0,0,cv.width,cv.height));
      const box=$('scan-output');
      if(!result?.recognized){box.textContent='⚪ Невизначено. '+(result?.reason||'Кольорові свічки не розпізнані.');return;}
      const direction=result.visualDirection==='up'?'↑ Зростання вже на фото':
        result.visualDirection==='down'?'↓ Падіння вже на фото':'— Боковий рух / невизначено';
      box.textContent='🕒 МИНУЛІ СВІЧКИ: '+direction+'\nЗнайдено приблизно '+result.candidates+
        ' свічкоподібних елементів.\n'+result.observedDirection+
        '\n⚠️ Це геометрія знімка, НЕ напрям наступної хвилини. Помилково можуть розпізнатися індикатори та написи.';
    }catch(e){$('scan-output').textContent='⚠️ '+String(e.message||'Не вдалося прочитати пікселі.');}
  }
  function setCloudLabel(label,ready=false){
    $('cloud-indicator').textContent=label;
    $('cloud-indicator').classList.toggle('safe',ready);
  }
  function cloudEndpoint(){
    const raw=$('cloud-endpoint').value.trim();
    const url=new URL(raw);
    // User-supplied code and photo must never go to arbitrary URLs or localhost.
    if(url.protocol!=='https:'||!url.hostname.endsWith('.vercel.app')||
      url.username||url.password||url.port||url.pathname!=='/'||url.search||url.hash)
      throw Error('Потрібна HTTPS-адреса проєкту на *.vercel.app без шляху й параметрів.');
    return url.origin;
  }
  function updateAIButton(){
    $('run-pocket-ai').disabled=!state.image||state.loading;
    if(!state.image) $('ai-status').textContent='Завантаж фото для аналізу.';
    else if(state.loading) $('ai-status').textContent='Хмарний JEV аналізує обрізаний графік…';
    else if(!state.cloudReady) $('ai-status').textContent='Фото завантажено. Спочатку підключи хмарний JEV вище.';
  }
  async function connectCloud(){
    const access=$('cloud-access').value.trim();
    state.cloudReady=false;updateAIButton();
    if(access.length<24){$('cloud-status').textContent='Код доступу має містити щонайменше 24 символи.';return;}
    let endpoint;
    try{endpoint=cloudEndpoint();}
    catch(e){$('cloud-status').textContent=String(e.message||e);return;}
    $('cloud-connect').disabled=true;
    $('cloud-status').textContent='Перевіряємо API та доступ до моделі…';
    try{
      const response=await fetch(endpoint+'/api/chart-health',{
        method:'GET',headers:{'X-JEV-Access':access},cache:'no-store',
        signal:AbortSignal.timeout(14000)});
      const data=await response.json().catch(()=>({}));
      if(!response.ok||data.ready!==true)
        throw Error(data.error||'Хмарний API недоступний (HTTP '+response.status+').');
      state.cloudReady=true;state.provider=String(data.provider||'AI');
      state.model=String(data.model||'');
      try{sessionStorage.setItem(CLOUD_SESSION_KEY,JSON.stringify({endpoint,access}));}catch{}
      setCloudLabel('☁️ JEV · '+state.provider+' · готовий',true);
      $('cloud-status').textContent='✅ Pocket API та '+state.provider+' підключено. '+(data.notice||'Перевірка каталогу не гарантує успіх аналізу фото.');
      if(state.image)$('ai-status').textContent='Можна надіслати обрізане фото до хмарного JEV.';
    }catch(e){
      setCloudLabel('☁️ JEV · немає з’єднання',false);
      $('cloud-status').textContent='⚠️ '+String(e.message||e)+'. Перевір код і налаштування Vercel.';
    }finally{$('cloud-connect').disabled=false;updateAIButton();}
  }
  function forgetCloud(){
    try{sessionStorage.removeItem(CLOUD_SESSION_KEY);}catch{}
    $('cloud-access').value='';
    state.cloudReady=false;state.provider='';state.model='';
    setCloudLabel('☁️ JEV · не підключено');
    $('cloud-status').textContent='Код із цієї вкладки очищено.';
    updateAIButton();
  }
  async function runAI(){
    if(state.loading||!state.image)return;
    const pref=getPrefs();
    if(!pairValid(pref.pair)){toast('Вкажи коректну пару.');return;}
    if(!Number.isFinite(pref.payout)||pref.payout<=0||pref.payout>100||
      !Number.isFinite(pref.stake)||pref.stake<=0||pref.stake>100000){
      toast('Перевір виплату та демосуму.');return;
    }
    if(!state.cloudReady){
      $('ai-status').textContent='⚠️ Не підключено хмарний JEV. Введи код і натисни «Перевірити підключення».';
      toast('Спочатку підключи хмарний JEV.');return;
    }
    state.ai=null;renderVerdict(null);
    state.loading=true;updateAIButton();
    try{
      const endpoint=cloudEndpoint(),access=$('cloud-access').value.trim();
      if(access.length<24)throw Error('Не вказано код доступу JEV.');
      const image=croppedCanvas().toDataURL('image/jpeg',.82).split(',')[1];
      if(!image||image.length>2800000)throw Error('Виділене зображення завелике. Обери меншу область.');
      const response=await fetch(endpoint+'/api/pocket-vision',{
        method:'POST',headers:{'Content-Type':'application/json','X-JEV-Access':access},
        body:JSON.stringify({pair:pref.pair,chart_timeframe_seconds:pref.timeframe,
          expiry_seconds:pref.expiry,payout_pct:pref.payout,image}),
        cache:'no-store',signal:AbortSignal.timeout(34000)});
      const data=await response.json().catch(()=>({}));
      if(!response.ok)throw Error(data.error||'Хмарний JEV повернув HTTP '+response.status);
      if(data.mode!=='screenshot_hypothesis'||data.orders_enabled!==false||
        data.quotes_verified!==false||data.broker_verified!==false||
        data.signal_validated!==false||!['UP','DOWN','STOP'].includes(data.direction)||
        typeof data.reason!=='string'||typeof data.risk!=='string')
        throw Error('Сервер повернув неповну або небезпечну відповідь. Гіпотезу не записано.');
      const direction=data.direction;
      const observations=Array.isArray(data.observations)?data.observations.filter(x=>typeof x==='string').slice(0,5):[];
      if(direction!=='STOP'&&observations.length<2)
        throw Error('Для UP/DOWN потрібні дві незалежні видимі ознаки на графіку.');
      state.ai={direction,reason:data.reason,risk:data.risk,observations,
        expiry:pref.expiry,timeframe:pref.timeframe,pair:pref.pair,
        provider:String(data.provider||state.provider||'cloud'),model:String(data.model||state.model||''),
        created:new Date().toISOString(),payout:pref.payout,stake:pref.stake,
        source:'pocket_cloud_screenshot',broker_verified:false,quotes_verified:false,
        signal_validated:false,picture_only:true};
      renderVerdict(state.ai);
      $('ai-status').textContent='✅ Хмарний JEV повернув '+direction+
        '. Це дослідницька гіпотеза лише за фото, без підтвердження брокера.';
      $('scan-output').textContent=observations.length?'ОЗНАКИ НА ФОТО (AI, не перевірені котируваннями):\n'+
        observations.map((s,i)=>(i+1)+'. '+s).join('\n'):'AI не встановив достатньо ознак для напрямку. Рішення STOP.';
    }catch(e){
      state.ai=null;
      renderVerdict(null,'Хмарна модель не дала перевірюваного висновку.');
      $('ai-status').textContent='⚠️ '+String(e.message||e)+'. Демопрогноз не створено.';
    }finally{state.loading=false;updateAIButton();}
  }
  function recordPaper(){
    const a=state.ai;
    if(!a||!['UP','DOWN','STOP'].includes(a.direction))return;
    const rows=localJournal();
    const id=(typeof crypto!=='undefined'&&crypto.randomUUID)?crypto.randomUUID():
      String(Date.now())+':'+Math.random().toString(36).slice(2);
    rows.unshift({id,...a,expiresAt:new Date(Date.now()+a.expiry*1000).toISOString(),
      outcome:a.direction==='STOP'?'skipped':'pending',manuallyReported:true});
    if(!saveJournal(rows)){toast('Пам’ять браузера заповнена.');return;}
    $('save-paper').disabled=true;
    toast(a.direction==='STOP'?'STOP збережено як утримання від прогнозу.':
      'Гіпотеза записана. Перевір результат після експірації.');
  }
  function outcome(id,value){
    if(!['hit','miss','tie','void'].includes(value))return;
    const rows=localJournal(),row=rows.find(x=>x.id===id);
    if(!row||row.outcome!=='pending'||Date.now()<Date.parse(row.expiresAt))return;
    row.outcome=value;row.checkedAt=new Date().toISOString();row.manuallyReported=true;
    if(saveJournal(rows))renderJournal();
  }
  function renderJournal(){
    const rows=localJournal(),settled=rows.filter(x=>x.outcome==='hit'||x.outcome==='miss');
    const hit=settled.filter(x=>x.outcome==='hit').length;
    const ties=rows.filter(x=>x.outcome==='tie').length;
    const skipped=rows.filter(x=>x.direction==='STOP').length;
    const pnl=settled.reduce((n,r)=>n+(r.outcome==='hit'?r.stake*r.payout/100:-r.stake),0);
    const grid=$('history-summary');grid.replaceChildren();
    [['Гіпотез / STOP',rows.length+' / '+skipped],['WIN / LOSS / TIE',hit+' / '+(settled.length-hit)+' / '+ties],
      ['Частка WIN серед вирішених',settled.length?fmt(hit/settled.length*100,1)+' %':'—'],
      ['Умовний P&L',settled.length?fmt(pnl)+' $':'—']].forEach(([label,val])=>{
      const box=document.createElement('div');box.className='stat';
      const sm=document.createElement('small');sm.textContent=label;
      const st=document.createElement('strong');st.textContent=String(val);
      box.append(sm,st);grid.append(box);
    });
    const groups=new Map();
    for(const entry of rows){
      const key=entry.pair+' · '+entry.expiry+' с';
      if(!groups.has(key))groups.set(key,{win:0,loss:0,tie:0,stop:0,pnl:0});
      const g=groups.get(key);
      if(entry.direction==='STOP'){g.stop++;continue;}
      if(entry.outcome==='tie'){g.tie++;continue;}
      if(entry.outcome==='hit'){g.win++;g.pnl+=entry.stake*entry.payout/100;}
      if(entry.outcome==='miss'){g.loss++;g.pnl-=entry.stake;}
    }
    const byPair=$('history-by-pair');byPair.replaceChildren();
    if(!groups.size){const p=document.createElement('p');p.className='hint';p.textContent='Немає гіпотез для аналізу.';byPair.append(p);}
    else for(const [name,g] of groups){
      const decided=g.win+g.loss;
      const card=document.createElement('div');card.className='journal-card';
      const title=document.createElement('strong');title.textContent=name;
      const desc=document.createElement('small');desc.textContent='WIN '+g.win+' · LOSS '+g.loss+
        ' · TIE '+g.tie+' · STOP '+g.stop+' · '+(decided?fmt(g.win/decided*100,1)+'% WIN':'немає оцінених')+
        ' · P&L '+fmt(g.pnl)+' $'+(decided<30?' · Мала вибірка (<30 WIN/LOSS)':'');
      card.append(title,desc);byPair.append(card);
    }
    const list=$('journal-list');list.replaceChildren();
    if(!rows.length){const p=document.createElement('p');p.className='notice';
      p.textContent='Ще немає демогіпотез. Завантаж скріншот і отримай відповідь JEV.';list.append(p);return;}
    rows.forEach(row=>{
      const card=document.createElement('article');card.className='journal-card';
      const content=document.createElement('div');
      const title=document.createElement('strong');title.textContent=
        (row.direction==='UP'?'↑ ВГОРУ':row.direction==='DOWN'?'↓ ВНИЗ':'⏸ СТОП')+' · '+row.pair;
      const time=document.createElement('small');time.textContent=
        new Date(row.created).toLocaleString('uk-UA')+' · '+row.timeframe+' с/свічка · експірація '+row.expiry+' с';
      const reason=document.createElement('small');reason.textContent=row.reason||'';
      const stateText=document.createElement('small');stateText.textContent='Статус: '+
        ({pending:'очікує ручної перевірки',hit:'WIN (зі слів користувача)',miss:'LOSS (зі слів користувача)',
          tie:'TIE (зі слів користувача)',skipped:'утримання (STOP)',void:'скасовано'}[row.outcome]||'невідомий');
      content.append(title,time,reason,stateText);card.append(content);
      if(row.outcome==='pending'){
        const actions=document.createElement('div');actions.className='actions';
        const waiting=Date.now()<Date.parse(row.expiresAt);
        [['hit','✓ WIN'],['miss','✕ LOSS'],['tie','= TIE'],['void','Скасувати']].forEach(([value,label])=>{
          const b=document.createElement('button');b.type='button';b.className='btn';
          b.textContent=label;b.disabled=waiting;b.addEventListener('click',()=>outcome(row.id,value));
          actions.append(b);
        });
        if(waiting){const sm=document.createElement('small');
          sm.textContent='Кнопки доступні після експірації.';actions.append(sm);}
        card.append(actions);
      }
      list.append(card);
    });
  }
  function exportJournal(){
    const blob=new Blob([JSON.stringify({mode:'manual_pocket_paper',exportedAt:new Date().toISOString(),
      independent_quotes_verified:false,results_broker_verified:false,entries:localJournal()},null,2)],
      {type:'application/json'});
    const url=URL.createObjectURL(blob);const a=document.createElement('a');
    a.href=url;a.download='crypto-myshka-pocket-demo.json';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),2000);
  }
  async function clipboardPhoto(){
    try{
      if(!navigator.clipboard?.read){toast('У цьому браузері встав фото через Ctrl+V.');return;}
      for(const item of await navigator.clipboard.read()){
        const type=item.types.find(t=>t.startsWith('image/'));
        if(type){const b=await item.getType(type);loadImage(new File([b],'clipboard.png',{type:b.type}));return;}
      }toast('У буфері немає фото.');
    }catch{toast('Доступ до буфера заборонено. Використай Ctrl+V або файл.');}
  }
  function init(){
    document.body.addEventListener('click',e=>{
      const btn=e.target.closest('button[data-go]');if(btn)route(btn.dataset.go);
    });
    window.addEventListener('hashchange',()=>route(location.hash.replace('#','')));
    $('pocket-pair').addEventListener('change',()=>{
      $('custom-pair-wrap').hidden=$('pocket-pair').value!=='custom';showMath();
    });
    ['custom-pair','pocket-timeframe','pocket-expiry','pocket-payout','pocket-stake'].forEach(id=>
      $(id).addEventListener('input',showMath));
    $('pocket-photo').addEventListener('change',e=>{const f=e.target.files?.[0];if(f)loadImage(f);e.target.value='';});
    $('paste-photo').addEventListener('click',clipboardPhoto);
    document.addEventListener('paste',e=>{
      if(e.target?.closest?.('input,textarea'))return;
      const file=Array.from(e.clipboardData?.items||[]).find(i=>i.type.startsWith('image/'))?.getAsFile();
      if(file){e.preventDefault();route('analysis');loadImage(file);}
    });
    $('clear-photo').addEventListener('click',()=>{
      state.image=null;state.crop=null;state.filename='';state.ai=null;
      $('photo-stage').hidden=true;$('empty-photo').hidden=false;resetScan();updateAIButton();
    });
    $('auto-crop').addEventListener('click',pickAutoCrop);
    $('reset-crop').addEventListener('click',()=>{state.crop=cropFallback();drawCanvas();resetScan();});
    $('scan-pixels').addEventListener('click',scanPixels);
    $('cloud-connect').addEventListener('click',connectCloud);
    $('cloud-forget').addEventListener('click',forgetCloud);
    $('cloud-endpoint').addEventListener('input',()=>{state.cloudReady=false;updateAIButton();});
    $('cloud-access').addEventListener('input',()=>{state.cloudReady=false;updateAIButton();});
    $('run-pocket-ai').addEventListener('click',runAI);
    $('save-paper').addEventListener('click',recordPaper);
    $('export-journal').addEventListener('click',exportJournal);
    $('clear-journal').addEventListener('click',()=>{
      if(!confirm('Очистити всі локальні демозаписи Pocket Lab?'))return;
      try{localStorage.removeItem(JOURNAL_KEY);}catch{}renderJournal();toast('Деможурнал очищено.');
    });
    if ('serviceWorker' in navigator && location.protocol==='https:') {
      navigator.serviceWorker.register('./myshka-sw.js').catch(()=>{});
    }
    installPointer();showMath();updateAIButton();renderVerdict(null);
    route(SCREENS.has(location.hash.slice(1))?location.hash.slice(1):'home');
    // A saved tab-only token is sufficient to re-check the model catalog.
    // With no token, publicly probe only route existence; never send a screenshot.
    setCloudLabel('☁️ JEV · не підключено');
    try{
      const saved=JSON.parse(sessionStorage.getItem(CLOUD_SESSION_KEY)||'null');
      if(saved&&saved.endpoint&&saved.access){
        $('cloud-endpoint').value=saved.endpoint;
        $('cloud-access').value=saved.access;
        connectCloud();
      }
    }catch{}
    setInterval(()=>{if(!$('screen-history').hidden)renderJournal();},15000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
  window.cryptoMyshkaPocket={getPrefs,getJournal:localJournal};
})();
