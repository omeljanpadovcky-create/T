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
    dragStart:null,dragging:false,ai:null,cloudReady:false,model:'',provider:'',loading:false,
    lastError:'',lastErrorCode:'',localReport:null,localBusy:false,imageRevision:0};
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
  function localTrendLabel(report){
    if(!report||report.reliable!==true)return '⚠️ СВІЧКИ НЕ РОЗПІЗНАНО НАДІЙНО';
    if(report.trendState==='sideways')return '↔ БОКОВИЙ РУХ НА ФОТО';
    if(report.trendState==='mixed')return '↕ СУПЕРЕЧЛИВИЙ РУХ НА ФОТО';
    if(report.direction==='up')return '↑ МИНУЛИЙ РУХ УГОРУ';
    if(report.direction==='down')return '↓ МИНУЛИЙ РУХ УНИЗ';
    return '⏸ ЧІТКОГО НАПРЯМУ НЕМАЄ';
  }
  function renderVerdict(answer,notice){
    const heading=$('ai-direction'),reason=$('ai-reason'),risk=$('ai-risk'),meta=$('ai-meta');
    const direction=answer&&['UP','DOWN','STOP'].includes(answer.direction)?answer.direction:'NONE';
    const local=!answer?state.localReport:null;
    const overline=$('ai-verdict')?.querySelector('.overline');
    if(overline)overline.textContent=local?'РЕЗУЛЬТАТ СКАНУВАННЯ ФОТО · НЕ ПРОГНОЗ':
      'ОЦІНКА НА НАСТУПНУ ЕКСПІРАЦІЮ';
    if(local){
      heading.textContent='🔎 ЛОКАЛЬНО · '+localTrendLabel(local);
      heading.className='stop';
      reason.textContent=(local.message||'Свічки на фото не вдалося впевнено оцінити')+
        '. Розпізнано '+(local.candidates||0)+' можливих свічкових елементів.'+
        (local.structureText?' '+local.structureText:'');
      risk.textContent='⚠️ Це лише спостереження минулого руху. '+
        'Точність розпізнавання не є точністю прогнозів. '+
        'За одним скриншотом неможливо перевірити майбутню експірацію чи OTC-котирування.';
      meta.textContent='Локальний розбір готовий · без API та грошей · '+
        (state.lastErrorCode==='PROVIDER_CREDITS'?'хмарна модель недоступна через квоту · ':'')+
        'не AI-прогноз, не рекомендація BUY/SELL.';
    }else{
      const fromBrowser=answer?.source==='pocket_browser_hypothesis';
      const label=fromBrowser?' · AI на ПК (демо)':' · гіпотеза JEV';
      heading.textContent=direction==='UP'?'↑ BUY'+label:
        direction==='DOWN'?'↓ SELL'+label:
        direction==='STOP'?'⏸ СТОП · утриматися':'⏳ ОЧІКУЄМО АНАЛІЗУ JEV';
      heading.className=direction==='UP'?'up':direction==='DOWN'?'down':'stop';
      reason.textContent=answer?.reason||notice||
        'Скріншот не завантажено. Додай фото — локальний розбір з’явиться автоматично.';
      risk.textContent=answer?.risk?'Ризик: '+answer.risk:'';
      meta.textContent=answer?'Джерело: '+(answer.source==='pocket_browser_hypothesis'?
          'локальна модель Chrome на цьому ПК':'хмарна модель')+
        ' · '+(answer.provider||'AI')+' · горизонт '+answer.expiry+
        ' с · OTC-котирування незалежно не перевірені · результат НЕ гарантується.':'';
    }
    $('save-paper').disabled=!state.ai;
    window.dispatchEvent(new CustomEvent('crypto-myshka-jev-verdict-change'));
  }
  function getScreenshotHypothesis(){
    const a=state.ai;
    if(!a||!['pocket_cloud_screenshot','pocket_browser_hypothesis'].includes(a.source)||
       (a.source==='pocket_cloud_screenshot'&&!state.cloudReady)||
       !['UP','DOWN','STOP'].includes(a.direction))return null;
    const p=getPrefs();
    if(a.pair!==p.pair||a.timeframe!==p.timeframe||a.expiry!==p.expiry)return null;
    return {direction:a.direction,created:a.created,expiry:a.expiry,source:a.source,
      provider:a.provider,broker_verified:false,quotes_verified:false,signal_validated:false};
  }
  function imageStatus(text){$('image-info').textContent=text;}
  function resetScan(text){
    $('scan-output').textContent=text||'Локальний сканер описує минулі свічки. Жодних прогнозів без перевіреної відповіді JEV.';
    state.imageRevision++;
    state.ai=null;state.lastError='';state.lastErrorCode='';state.localReport=null;
    renderVerdict(null);updateAIButton();
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
    resetScan('Автоматично аналізуємо вже намальовані свічки на вибраній області…');
    // The old workflow accepted a screenshot and immediately produced a visual
    // assessment. Restore that low-friction path without silently spending API credits.
    scanPixels();
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
          ' · Минулий рух уже перевірено локально. Якщо рамка захопила меню — обведи лише свічки; аналіз повториться сам.');
        updateAIButton();toast('Фото проаналізовано локально. AI на ПК запуститься сам, якщо вже встановлений.');
        void maybeAutoBrowserVision(state.imageRevision);
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
      drawCanvas();
      resetScan('Аналізуємо заново після зміни області…');
      scanPixels();
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
  // No network, no inference model, no future prices: diagnostic of ALREADY DRAWN candles.
  // This remains useful when external cloud vision is blocked by credits or quota.
  function scanPixels(){
    state.localReport=null;
    const box=$('scan-output');
    try{
      const canvas=croppedCanvas();
      const scanner=window.cryptoMyshkaPhotoScan;
      if(!scanner?.analyzePixels)throw Error('Локальний сканер свічок не завантажився. Онови сторінку.');
      const result=scanner.analyzePixels(canvas.getContext('2d',{willReadFrequently:true})
        .getImageData(0,0,canvas.width,canvas.height));
      if(!result?.recognized){
        const reason=String(result?.reason||'Свічки не розпізнано').slice(0,320);
        state.localReport={kind:'historical_only',direction:'unknown',trendState:'unreliable',
          reliable:false,candidates:Math.max(0,Number(result?.candidates)||0),message:reason};
        box.textContent='🟠 ЛОКАЛЬНО · НЕДОСТАТНЬО ДАНИХ\n'+reason+
          '\nВиділи лише свічки на графіку й повтори. Рух наступної свічки невідомий.';
        return state.localReport;
      }
      const reliable=result.reliable===true&&result.partial!==true;
      const pastDirection=reliable&&['up','down'].includes(result.visualDirection)?
        result.visualDirection:'unknown';
      const trendState=result.trendState||(!reliable?'unreliable':
        pastDirection!=='unknown'?pastDirection:'mixed');
      const label=pastDirection==='up'?'↑ Зростання вже на фото':
        pastDirection==='down'?'↓ Падіння вже на фото':
        trendState==='sideways'?'↔ Боковий рух · немає вираженого тренду':
        trendState==='mixed'?'↕ Суперечливі ділянки · напрям не підтверджено':
        '— Напрям історичного руху ненадійний';
      const count=Math.max(0,Math.round(Number(result.candidates)||0));
      const quality=Number.isFinite(Number(result.qualityScore))?
        Math.max(0,Math.min(100,Math.round(Number(result.qualityScore)))):null;
      const green=Math.max(0,Math.round(Number(result.green)||0));
      const red=Math.max(0,Math.round(Number(result.red)||0));
      const recent=green+red>0?'Останні розпізнані свічки: зелених '+green+
        ', червоних '+red+'. ':'';
    const structure=result.structure&&reliable?result.structure:null;
    const shortLabel=structure?.shortMove==='higher'?'Останні 6 свічок вище попередніх 6':
      structure?.shortMove==='lower'?'Останні 6 свічок нижче попередніх 6':
      structure?'Середня висота останніх 6 свічок майже не змінилась':'';
    const highLow=structure?.highShape==='higher'&&structure?.lowShape==='higher'?
      'У виділеній області вищі максимуми й мінімуми.':
      structure?.highShape==='lower'&&structure?.lowShape==='lower'?
      'У виділеній області нижчі максимуми й мінімуми.':
      structure?'Максимуми й мінімуми не підтверджують один напрям.':'';
    const recentColors=structure?
      'Останні шість: '+structure.green+' зелених, '+structure.red+' червоних. ':'';
    const structureText=structure?(shortLabel+'. '+highLow+' '+recentColors).trim():'';
      const qualityText=quality!==null?'Регулярність виявлених свічкоподібних контурів: '+quality+
        '/100 (НЕ точність прогнозів і НЕ доказ напряму). ':'';
      const message=(result.observedDirection||'Виявлено кольорові свічки.').slice(0,280);
      state.localReport={kind:'historical_only',direction:pastDirection,trendState,reliable,
        candidates:count,qualityScore:quality,green,red,message,structureText,
        checkedAt:new Date().toISOString()};
      box.textContent='🧠 JEV LITE · ЛОКАЛЬНО БЕЗ API\nМИНУЛІ СВІЧКИ: '+label+
        '\nЗнайдено близько '+count+' свічкоподібних елементів.\n'+qualityText+recent+
        '\n'+message+(structureText?'\n'+structureText:'')+'\n⚠️ Це ЛИШЕ опис минулих пікселів на фото. '+
        'Немає доступу до OTC-котирувань і майбутньої свічки. '+
        'Локальний сканер НЕ створює торговий сигнал BUY / SELL. '+
        'Хмарний AI може бути недоступний через квоту.';
      return state.localReport;
    }catch(e){
      const message=String(e?.message||'Не вдалося прочитати свічки').slice(0,250);
      state.localReport={kind:'historical_only',direction:'unknown',reliable:false,message};
      box.textContent='⚠️ ЛОКАЛЬНИЙ СКАНЕР: '+message+
        '\nЖодного результату на наступну експірацію немає.';
      return state.localReport;
    }finally{
      if(!state.ai)renderVerdict(null);
      window.dispatchEvent(new CustomEvent('crypto-myshka-analysis-state-change'));
    }
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
  function getAnalysisState(){
    return {hasImage:Boolean(state.image),cloudReady:Boolean(state.cloudReady),
      loading:Boolean(state.loading),hasHypothesis:Boolean(state.ai),
      lastError:state.lastError,lastErrorCode:state.lastErrorCode,
      localReport:state.localReport};
  }
  function updateAIButton(){
    $('run-pocket-ai').disabled=!state.image||state.loading;
    const desktopButton=$('local-ai-vision');
    if(desktopButton)desktopButton.disabled=!state.image||state.loading;
    if(state.loading)
      $('ai-status').textContent=state.localBusy?
        'Локальна AI-модель аналізує фото на цьому комп’ютері…':
        'Хмарний JEV аналізує обрізаний графік…';
    else if(!state.image)
      $('ai-status').textContent=state.cloudReady?
        '✅ Каталог API доступний. Додай свіжий скриншот: підключення не створює сигнал.':
        'Додай скриншот графіка й підключи хмарний JEV.';
    else if(state.lastError)
      $('ai-status').textContent='⚠️ ПОМИЛКА JEV'+
        (state.lastErrorCode?' ['+state.lastErrorCode+']':'')+': '+state.lastError+
        ' Фото залишилось завантаженим; після усунення проблеми повтори аналіз.';
    else if(state.ai?.source==='pocket_browser_hypothesis')
      $('ai-status').textContent=state.ai.direction==='STOP'?
        '⏸ Локальна AI-модель утрималася: '+state.ai.reason:
        '✅ Вбудована модель Chrome повернула '+state.ai.direction+
        '. Лише дослідницька гіпотеза за фото, без перевірених OTC-котирувань.';
    else if(!state.cloudReady)
      $('ai-status').textContent='Фото готове. Для хмарного AI потрібна квота. За підтримки браузера можна перевірити локальний AI на ПК.';
    else if(state.ai)
      $('ai-status').textContent=state.ai.direction==='STOP'?
        '⏸ JEV утримався: '+state.ai.reason:
        '✅ Хмарний JEV повернув '+state.ai.direction+
        '. Це дослідницька гіпотеза без перевірки котирувань.';
    else
      $('ai-status').textContent='✅ Фото й API готові. Натисни «Аналізувати фото JEV».';
    window.dispatchEvent(new CustomEvent('crypto-myshka-analysis-state-change'));
  }
  async function connectCloud(){
    const access=$('cloud-access').value.trim();
    state.cloudReady=false;state.lastError='';state.lastErrorCode='';
    state.ai=null;renderVerdict(null,'Підключення AI перевіряється. Поки що гіпотези немає.');
    updateAIButton();
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
      setCloudLabel('☁️ JEV · '+state.provider+' · API на звʼязку',true);
      $('cloud-status').textContent='✅ Каталог '+state.provider+
        ' відповідає. Це ще не аналіз фото і не підтверджений сигнал. '+
        (data.notice||'Доступ до обробки фото може залежати від квоти.');
      renderVerdict(null,'API доступний, але прогнозу ще немає. Додай свіжий скриншот графіка й натисни «Аналізувати фото JEV».');
    }catch(e){
      setCloudLabel('☁️ JEV · немає з’єднання',false);
      $('cloud-status').textContent='⚠️ '+String(e.message||e)+'. Перевір код і налаштування Vercel.';
    }finally{$('cloud-connect').disabled=false;updateAIButton();}
  }
  function forgetCloud(){
    try{sessionStorage.removeItem(CLOUD_SESSION_KEY);}catch{}
    state.ai=null;state.lastError='';state.lastErrorCode='';
    renderVerdict(null,'Підключення вимкнене — нових гіпотез немає.');
    $('cloud-access').value='';
    state.cloudReady=false;state.provider='';state.model='';
    setCloudLabel('☁️ JEV · не підключено');
    $('cloud-status').textContent='Код із цієї вкладки очищено.';
    updateAIButton();
  }
  // Completely local: automatically use a previously downloaded Chrome model,
  // but never trigger a multi-GB model download or paid endpoint without a click.
  async function maybeAutoBrowserVision(revision){
    const vision=window.cryptoMyshkaBrowserVision;
    const note=$('local-ai-status');
    if(!vision?.availability){
      note.textContent='На цьому браузері локальна AI-модель для фото недоступна. '+
        'Базовий аналіз свічок уже виконано безплатно.';
      return;
    }
    let status='unavailable';
    try{status=await vision.availability();}catch{}
    if(revision!==state.imageRevision||!state.image)return;
    if(status==='available'&&!state.loading){
      note.textContent='✅ Локальна AI-модель уже встановлена. Автоматично аналізуємо фото без API…';
      await runBrowserAI();
    }else if(status==='downloadable'||status==='downloading'){
      note.textContent='Локальна AI-модель підтримується, але ще не встановлена. '+
        'Натисни «AI на ПК», якщо хочеш завантажити модель у браузер.';
    }else{
      note.textContent='На цьому пристрої немає підтримуваної локальної AI-моделі для фото. '+
        'Сканер свічок працює без ключів; хмарний APInex має обмеження квоти.';
    }
  }
  async function runBrowserAI(){
    const note=$('local-ai-status');
    if(state.loading||!state.image){note.textContent='Спочатку додай фото свічкового графіка.';return;}
    if(!window.cryptoMyshkaBrowserVision?.analyze){
      note.textContent='⚠️ Модуль локального AI не завантажився. Онови сторінку.';
      return;
    }
    const prefs=getPrefs(),revision=state.imageRevision;
    state.ai=null;state.localBusy=true;state.loading=true;
    state.lastError='';state.lastErrorCode='';
    renderVerdict(null);updateAIButton();
    try{
      const answer=await window.cryptoMyshkaBrowserVision.analyze(croppedCanvas(),prefs,
        message=>{if(revision===state.imageRevision)note.textContent='⏳ '+String(message).slice(0,220);});
      if(revision!==state.imageRevision||!state.image){
        note.textContent='Фото або рамка змінилися під час аналізу. Стару оцінку скинуто.';
        return;
      }
      if(answer.orders_enabled!==false||answer.signal_validated!==false||
         answer.quotes_verified!==false||answer.broker_verified!==false||
         !['UP','DOWN','STOP'].includes(answer.direction))
        throw Error('Локальна модель не повернула безпечну дослідницьку відповідь.');
      if(answer.direction!=='STOP'&&(!Array.isArray(answer.observations)||answer.observations.length<2))
        throw Error('Для напрямку потрібні щонайменше дві видимі ознаки.');
      state.ai={direction:answer.direction,reason:answer.reason,risk:answer.risk,
        observations:answer.observations||[],expiry:prefs.expiry,timeframe:prefs.timeframe,
        pair:prefs.pair,payout:prefs.payout,stake:prefs.stake,
        provider:'Chrome Gemini Nano (на пристрої)',model:'browser',
        created:new Date().toISOString(),source:'pocket_browser_hypothesis',
        signal_validated:false,quotes_verified:false,broker_verified:false,
        picture_only:true};
      renderVerdict(state.ai);
      note.textContent='✅ Фото оброблено локально в Chrome, без APInex. '+(
        answer.direction==='STOP'?'Обґрунтованого напрямку немає.':
        'Гіпотеза '+answer.direction+' тільки для ручного DEMO-тесту, не реальна ставка.');
    }catch(e){
      if(revision!==state.imageRevision||!state.image)return;
      state.ai=null;
      note.textContent='⚠️ '+String(e?.message||'Вбудований AI недоступний').slice(0,320)+
        ' Безкоштовний сканер минулих свічок залишається доступним.';
      renderVerdict(null);
    }finally{
      state.localBusy=false;state.loading=false;updateAIButton();
    }
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
    state.ai=null;state.lastError='';state.lastErrorCode='';renderVerdict(null);
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
      if(!response.ok){
        const message=typeof data.error==='string'?data.error:'Хмарний JEV повернув HTTP '+response.status;
        const err=new Error(message);err.code=typeof data.code==='string'?data.code:'HTTP_'+response.status;
        throw err;
      }
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
      state.lastError='';state.lastErrorCode='';
      renderVerdict(state.ai);
      $('scan-output').textContent=observations.length?'ОЗНАКИ НА ФОТО (AI, не перевірені котируваннями):\n'+
        observations.map((s,i)=>(i+1)+'. '+s).join('\n'):'AI не встановив достатньо ознак для напрямку. Рішення STOP.';
    }catch(e){
      state.ai=null;
      state.lastError=e?.name==='TimeoutError'?
        'Запит не завершився за 34 секунди. Можливі затримка або ліміт APInex.':
        e?.name==='TypeError'?
          'Не вдалося виконати мережевий запит. Перевір зʼєднання, CORS або доступність Vercel.':
          String(e?.message||'Невідома помилка аналізу.');
      state.lastErrorCode=typeof e?.code==='string'?e.code.slice(0,40):
        e?.name==='TimeoutError'?'CLIENT_TIMEOUT':'';
      renderVerdict(null,'⚠️ '+state.lastError+
        '\\nСтарий результат не використовується. BUY/SELL не підсвічуються.');
      // A paid provider's HTTP 402/429 must not make the offline historical
      // image scanner unusable or silently create a fake AI trading hypothesis.
      if(['PROVIDER_CREDITS','PROVIDER_RATE_LIMIT','MODEL_NOT_FOUND',
          'MODEL_REQUEST_REJECTED','PROVIDER_UNAVAILABLE'].includes(state.lastErrorCode)){
        if(state.lastErrorCode==='PROVIDER_CREDITS')
          setCloudLabel('☁️ APInex · немає квоти для фото',false);
        scanPixels();
      }
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
    const rows=localJournal(),jevRows=rows.filter(x=>x.source!=='pocket_manual_demo'),
      manualRows=rows.filter(x=>x.source==='pocket_manual_demo');
    const settled=jevRows.filter(x=>x.outcome==='hit'||x.outcome==='miss');
    const manualSettled=manualRows.filter(x=>x.outcome==='hit'||x.outcome==='miss');
    const hit=settled.filter(x=>x.outcome==='hit').length;
    const ties=jevRows.filter(x=>x.outcome==='tie').length;
    const skipped=jevRows.filter(x=>x.direction==='STOP').length;
    const pnl=settled.reduce((n,r)=>n+(r.outcome==='hit'?r.stake*r.payout/100:-r.stake),0);
    const manualPnl=manualSettled.reduce((n,r)=>n+(r.outcome==='hit'?r.stake*r.payout/100:-r.stake),0);
    const grid=$('history-summary');grid.replaceChildren();
    [['JEV: гіпотези / STOP',jevRows.length+' / '+skipped],['JEV: WIN / LOSS / TIE',hit+' / '+(settled.length-hit)+' / '+ties],
      ['JEV: частка WIN',settled.length?fmt(hit/settled.length*100,1)+' %':'—'],
      ['JEV: умовний P&L',settled.length?fmt(pnl)+' $':'—'],
      ['Ручні BUY / SELL',manualRows.length+' записів'],
      ['Ручні WIN / LOSS / TIE',manualSettled.filter(x=>x.outcome==='hit').length+' / '+
        manualSettled.filter(x=>x.outcome==='miss').length+' / '+
        manualRows.filter(x=>x.outcome==='tie').length],
      ['Ручні: умовний P&L',manualSettled.length?fmt(manualPnl)+' $':'—']].forEach(([label,val])=>{
      const box=document.createElement('div');box.className='stat';
      const sm=document.createElement('small');sm.textContent=label;
      const st=document.createElement('strong');st.textContent=String(val);
      box.append(sm,st);grid.append(box);
    });
    const groups=new Map();
    for(const entry of jevRows){
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
        (row.source==='pocket_manual_demo'?'РУЧНА DEMO · ':'JEV · ')+
        (row.direction==='UP'?'↑ '+(row.source==='pocket_manual_demo'?'BUY':'ВГОРУ'):
         row.direction==='DOWN'?'↓ '+(row.source==='pocket_manual_demo'?'SELL':'ВНИЗ'):'⏸ СТОП')+' · '+row.pair;
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
    $('reset-crop').addEventListener('click',()=>{
      state.crop=cropFallback();drawCanvas();resetScan('Аналізуємо область…');scanPixels();
    });
    $('scan-pixels').addEventListener('click',scanPixels);
    $('cloud-connect').addEventListener('click',connectCloud);
    $('cloud-forget').addEventListener('click',forgetCloud);
    ['cloud-endpoint','cloud-access'].forEach(id=>$(id).addEventListener('input',()=>{
      state.cloudReady=false;state.ai=null;state.lastError='';state.lastErrorCode='';
      renderVerdict(null,'Параметри доступу змінені — перепідключи хмарний JEV.');
      updateAIButton();
    }));
    $('run-pocket-ai').addEventListener('click',runAI);
    $('local-ai-vision')?.addEventListener('click',runBrowserAI);
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
  window.cryptoMyshkaPocket={getPrefs,getJournal:localJournal,getScreenshotHypothesis,getAnalysisState};
})();
