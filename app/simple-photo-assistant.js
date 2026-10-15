/* Crypto Myshka: minimal, keyless screenshot explanation.
 * All calculations describe visible pixels, not a future trade or verified prices.
 */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const scanner=()=>window.cryptoMyshkaPhotoScan;
  const state={image:null,filename:'',bounds:null,drag:null,canvas:null,last:null};
  const round=n=>Number.isFinite(n)?Math.round(n):0;
  function setMessage(message){$('message').textContent=message;}
  function showReport(title,paragraph,stats=[],facts=[],warning=''){
    const result=$('result');result.hidden=false;
    $('data-analytics').hidden=true;
    $('minute-verdict').textContent='Напрям наступної M1-свічки (60 с) невідомий. Висновок нижче стосується лише свічок на фото, а не майбутньої експірації.';
    $('result-title').textContent=title;
    $('result-explain').textContent=paragraph;
    const tiles=$('result-stats');tiles.replaceChildren();
    stats.forEach(x=>{
      const item=document.createElement('div');item.className='stat';
      const value=document.createElement('strong');value.textContent=x.value;
      const label=document.createElement('small');label.textContent=x.label;
      item.append(value,label);tiles.append(item);
    });
    const list=$('result-facts');list.replaceChildren();
    facts.forEach(value=>{const item=document.createElement('li');item.textContent=value;list.append(item);});
    $('result-caution').textContent=warning||
      'Це розбір уже намальованого графіка, а не сигнал або ймовірність виграшу.';
  }
  // Small DATA-ANALYTICS presentation. Numbers are descriptive fractions
  // of detected coloured shapes; never fabricate future price probabilities.
  function renderDataAnalytics(report,trend){
    const box=$('data-analytics'),grid=$('analytics-grid');
    box.hidden=true;grid.replaceChildren();
    const a=report?.analytics;
    if(!a||!report.reliable||!a.total||!Number.isFinite(a.total.count)||!a.total.count)return;
    const pct=n=>Number.isFinite(n)?Math.round(n)+'%':'—';
    const groups=[
      ['Увесь видимий графік',a.total],
      ['Останні 12',a.recent12],
      ['Попередні 6',a.previous6],
      ['Останні 6',a.recent6]
    ];
    groups.forEach(([label,data])=>{
      if(!data||!Number.isFinite(data.count)||data.count<1)return;
      const card=document.createElement('div');card.className='analytics-card';
      const small=document.createElement('small');small.textContent=label;
      const title=document.createElement('strong');
      title.textContent=data.green+' зелених / '+data.red+' червоних';
      const counts=document.createElement('small');
      counts.textContent=data.count+' знайдених контурів · '+pct(data.greenPct)+' зелених';
      const track=document.createElement('div');track.className='analytics-track';
      track.setAttribute('role','img');
      track.setAttribute('aria-label',label+': '+data.green+
        ' зелених, '+data.red+' червоних');
      const greenBar=document.createElement('span');greenBar.className='analytics-green';
      greenBar.style.width=Math.max(0,Math.min(100,Number(data.greenPct)||0))+'%';
      const redBar=document.createElement('span');redBar.className='analytics-red';
      redBar.style.width=Math.max(0,Math.min(100,Number(data.redPct)||0))+'%';
      track.append(greenBar,redBar);
      card.append(small,title,track,counts);grid.append(card);
    });
    const previous=a.previous6,recent=a.recent6;
    const sufficient=previous?.count===6&&recent?.count===6;
    const compare=$('analytics-comparison');
    if(sufficient&&Number.isFinite(a.greenDeltaPp)){
      const delta=a.greenDeltaPp;
      compare.textContent='Порівняння двох останніх шісток: частка зелених '+
        (Math.abs(delta)<.01?'не змінилася':delta>0?'зросла на '+Math.round(delta)+
          ' відсоткових пунктів':'зменшилася на '+Math.round(Math.abs(delta))+
          ' відсоткових пунктів')+
        '. Це порівняння минулих свічок, не ймовірність наступної.';
    }else compare.textContent='Для порівняння останніх 12 свічок потрібні 12 чітко розпізнаних контурів.';
    const thirds=Array.isArray(a.thirds)?a.thirds:[];
    $('analytics-phases').textContent=thirds.length===3?
      'Три частини графіка (зліва направо): '+thirds.map((part,index)=>
        ['початок','середина','кінець'][index]+' — '+part.green+'/'+part.count+
        ' зелених ('+pct(part.greenPct)+')').join('; ')+'.':
      'Розподілу на три частини немає.';
    let issue='';
    if(a.contrast&&recent?.count===6){
      issue=recent.green>=4?
        'Важлива суперечність: останні 6 контурів переважно зелені, '+
        'але їхні рівні нижчі за попередні 6. Зелена свічка означає рух '+
        'усередині НЕЇ, а не те, що весь графік уже виріс.':
        'Важлива суперечність: останні 6 контурів переважно червоні, '+
        'але їхні рівні вищі за попередні 6. Червона свічка не доводить '+
        'спадного тренду всього графіка.';
    }else if(trend==='sideways'&&['higher','lower'].includes(a.recentLevel)){
      issue='На всьому фото боковик, але остання шістка розташована '+
        (a.recentLevel==='higher'?'вище':'нижче')+
        ' попередньої. Коротка зміна рівнів не обов’язково перетворює '+
        'весь боковик на тренд.';
    }
    const warning=$('analytics-contrast');
    warning.hidden=!issue;
    warning.textContent=issue;
    box.hidden=false;
  }
  function draw(){
    const canvas=state.canvas,img=state.image;
    if(!canvas||!img)return;
    const ctx=canvas.getContext('2d');
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.drawImage(img,0,0,canvas.width,canvas.height);
    // Manual selection is OPTIONAL. Full image is always the default.
    const b=state.bounds;
    if(!b)return;
    ctx.lineWidth=3;ctx.strokeStyle='#f6d17a';ctx.setLineDash([9,6]);
    ctx.strokeRect(b.x,b.y,b.w,b.h);ctx.setLineDash([]);
  }
  function imagePixels(area=null){
    const img=state.image,cv=state.canvas;
    if(!img||!cv)return null;
    const b=area||{x:0,y:0,w:cv.width,h:cv.height};
    const output=document.createElement('canvas');
    output.width=Math.max(1,round(b.w));
    output.height=Math.max(1,round(b.h));
    const ctx=output.getContext('2d',{willReadFrequently:true});
    ctx.drawImage(img,
      b.x/cv.width*img.naturalWidth,b.y/cv.height*img.naturalHeight,
      b.w/cv.width*img.naturalWidth,b.h/cv.height*img.naturalHeight,
      0,0,output.width,output.height);
    return ctx.getImageData(0,0,output.width,output.height);
  }
  function evaluateScreenshot(){
    const scan=scanner();
    if(!scan?.analyzePixels)throw Error('Модуль аналізу фото не завантажився.');
    const fullData=imagePixels();
    // Inspect every pixel first, even if the screenshot includes platform UI.
    const full=scan.analyzePixels(fullData);
    if(state.bounds){
      const selected=scan.analyzePixels(imagePixels(state.bounds));
      return {report:selected,full,method:'manual',
        area:state.bounds,autoCandidate:false};
    }
    // A whole-frame reading is preferred; if overlays contaminate it, locate
    // the main chart automatically using the *entire* screenshot.
    if(full?.recognized&&full.reliable)
      return {report:full,full,method:'whole',area:null,autoCandidate:false};
    const found=scan.findChartBounds?.(fullData);
    if(found&&found.w>=80&&found.h>=70){
      const candidate=scan.analyzePixels(imagePixels(found));
      if(candidate?.recognized && (!full?.recognized||
        (candidate.reliable&&!full.reliable) ||
        (candidate.reliable===full.reliable&&
          Number(candidate.qualityScore||0)>Number(full.qualityScore||0)+10))){
        return {report:candidate,full,method:'chart_auto',
          area:found,autoCandidate:true};
      }
    }
    return {report:full,full,method:'whole',area:null,autoCandidate:false};
  }
  function insightForStructure(report){
    const s=report?.structure;
    if(!s)return ['Недостатньо незалежних контурів, щоб окремо порівняти останні 12 свічок.'];
    const level=s.shortMove==='higher'?'вище':s.shortMove==='lower'?'нижче':'приблизно на тому самому рівні';
    const highs=s.highShape==='higher'?'вищими':s.highShape==='lower'?'нижчими':'схожими';
    const lows=s.lowShape==='higher'?'вищими':s.lowShape==='lower'?'нижчими':'схожими';
    const result=[
      'Останні шість елементів розташовані '+level+' за попередні шість.',
      'Верхні межі свічкоподібних елементів стали '+highs+
        ', а нижні — '+lows+'.'
    ];
    const last=s.green+s.red;
    if(last>0)result.push('Останні шість: '+s.green+' зелених ('+
      round(100*s.green/last)+'%) та '+s.red+' червоних ('+
      round(100*s.red/last)+'%). Це тільки недавня вибірка.');
    if(s.sameColor>=2)
      result.push('Наприкінці видно серію з '+s.sameColor+
        ' однаково забарвлених елементів; це не гарантує продовження тенденції.');
    return result;
  }
  function inspect(){
    if(!state.image||!state.canvas)return;
    let scan;
    try{scan=evaluateScreenshot();}
    catch(e){
      showReport('Не вдалося прочитати фото',
        String(e?.message||'Сталася помилка аналізу зображення.'));
      setMessage('Зображення не розпізнано. Спробуй новий скриншот.');
      return;
    }
    const {report,full,method}=scan;
    state.last=scan;
    const fullCount=Number(full?.candidates)||0;
    const scope=method==='manual'?'Обрано вручну лише частину зображення.':
      method==='chart_auto'?'Перевірено весь скриншот; меню та підписи відокремлено від основного поля графіка автоматично.':
        'Проаналізовано всю площу скриншота без ручного обведення.';
    const info=$('scan-scope');
    if(info)info.textContent=scope+' Розмір '+state.image.naturalWidth+'×'+
      state.image.naturalHeight+' пікселів.';
    if(!report?.recognized){
      showReport('Скриншот прочитано · свічки не підтверджені',
        'Мишка перевірила все зображення, але не змогла надійно відокремити свічки від графічних елементів інтерфейсу.',
        [],[scope,'На всьому зображенні знайдено '+fullCount+
          ' можливих кольорових контурів.',
          report?.reason||'Використай чіткіший скриншот або обведи лише поле графіка.']);
      setMessage('Фото перевірено повністю, однак достовірного розбору свічок немає.');
      return;
    }
    const green=Math.max(0,Number(report.totalGreen??report.green)||0);
    const red=Math.max(0,Number(report.totalRed??report.red)||0);
    const observed=green+red;
    const greenPct=observed>0?100*green/observed:null;
    const redPct=observed>0?100*red/observed:null;
    const trend=report.reliable===true?
      report.trendState||report.visualDirection:'unreliable';
    const title=trend==='up'?'На скриншоті видно зростання':
      trend==='down'?'На скриншоті видно падіння':
      trend==='sideways'?'На скриншоті переважає боковик':
      trend==='mixed'?'Видимий рух суперечливий':
      'Недостатньо даних для чіткого тренду';
    const why=trend==='up'?
        'Видимі пізніші свічкоподібні елементи розташовані вище за попередні: на графіку був висхідний рух.':
      trend==='down'?
        'Пізніші свічкоподібні елементи розташовані нижче за попередні: на графіку був спадний рух.':
      trend==='sideways'?
        'Ранні й пізні елементи змінюють висоту незначно, вираженої тенденції немає.':
      trend==='mixed'?
        'Різні частини зображення показують протилежні напрямки; загальний тренд не підтверджено.':
        'Частину елементів знайдено, але їхнє положення або регулярність не дають упевнено назвати тренд.';
    const stats=[
      {value:String(round(report.candidates||0)),label:'контурів на основному графіку'},
      {value:greenPct===null?'—':round(greenPct)+'%',label:'зелених серед усіх розпізнаних'},
      {value:redPct===null?'—':round(redPct)+'%',label:'червоних серед усіх розпізнаних'}
    ];
    const facts=[
      scope,
      'Виявлено '+round(report.candidates||0)+' свічкоподібних елементів: '+
        green+' зелених, '+red+' червоних.',
      'Загальний минулий напрям: '+String(report.observedDirection||'невизначений')+'.',
      ...insightForStructure(report),
      ...(typeof window.cryptoMyshkaPriceAction?.photoSummary==='function'?
        window.cryptoMyshkaPriceAction.photoSummary(report):[]),
      'M1 означає 60 секунд на одну свічку. Невідомо, чи остання намальована свічка вже завершена.'
    ];
    if(method==='chart_auto')
      facts.push('На повному скриншоті попередньо знайдено '+fullCount+
        ' кольорових контурів; для підсумку обрано автоматично відокремлений графік, щоб не рахувати меню.');
    const quality=Number(report.qualityScore);
    if(Number.isFinite(quality))facts.push('Оцінка геометрії контурів '+
      round(quality)+'/100 — не точність торгових прогнозів.');
    showReport(title,why,stats,facts,
      'Це локальне розпізнавання кольорів і положення свічок по всьому фото. '+
      'Не виконується розпізнавання тексту, котирувань чи чисел RSI/MACD на знімку. '+
      'Відсотки — частка розпізнаних кольорів, а НЕ шанс BUY/SELL чи рух ціни за наступні 60 секунд.');
    renderDataAnalytics(report,trend);
    setMessage('Готово. Мишка порівняла весь графік, останні 12 та останні 6 свічок — без вигаданих шансів.');
  }
  function drawAndInspect(){draw();inspect();}
  function upload(file){
    if(!file||!['image/jpeg','image/png','image/webp'].includes(file.type)||
      file.size>9*1024*1024||file.size<1){
      setMessage('Потрібен JPG, PNG або WebP розміром до 9 МБ.');return;
    }
    const reader=new FileReader();
    reader.onerror=()=>setMessage('Помилка читання фото.');
    reader.onload=()=>{
      const image=new Image();
      image.onerror=()=>setMessage('Файл не схожий на справжнє зображення.');
      image.onload=()=>{
        if(image.naturalWidth<140||image.naturalHeight<100||
           image.naturalWidth*image.naturalHeight>20000000){
          setMessage('Зображення занадто мале або велике.');return;
        }
        state.image=image;state.filename=file.name||'скриншот';
        const ratio=Math.min(1,960/image.naturalWidth,650/image.naturalHeight);
        const canvas=$('chart-canvas');
        canvas.width=Math.max(1,round(image.naturalWidth*ratio));
        canvas.height=Math.max(1,round(image.naturalHeight*ratio));
        state.canvas=canvas;state.bounds=null;state.last=null;
        $('canvas-area').hidden=false;
        $('filename').textContent=state.filename+' · '+image.naturalWidth+'×'+image.naturalHeight;
        drawAndInspect();
      };
      image.src=String(reader.result);
    };
    reader.readAsDataURL(file);
  }
  function pointerPosition(ev){
    const rect=state.canvas.getBoundingClientRect();
    if(!rect.width||!rect.height)return{x:0,y:0};
    return {x:Math.max(0,Math.min(state.canvas.width,(ev.clientX-rect.left)*state.canvas.width/rect.width)),
      y:Math.max(0,Math.min(state.canvas.height,(ev.clientY-rect.top)*state.canvas.height/rect.height))};
  }
  function init(){
    $('file-input').addEventListener('change',ev=>{
      const file=ev.target.files?.[0];
      if(file)upload(file);
      ev.target.value='';
    });
    $('paste-btn').addEventListener('click',async()=>{
      try{
        const items=await navigator.clipboard.read();
        const blob=await Promise.all(items.map(async item=>{
          const type=item.types.find(t=>t.startsWith('image/'));
          return type?item.getType(type):null;
        }));
        const file=blob.find(Boolean);
        if(!file)throw Error('У буфері немає зображення.');
        upload(file);
      }catch{
        setMessage('Встав фото через Ctrl+V (ПК) або обери файл через кнопку.');
      }
    });
    document.addEventListener('paste',ev=>{
      if(ev.target?.closest?.('input,textarea'))return;
      const item=Array.from(ev.clipboardData?.items||[]).find(i=>i.type.startsWith('image/'));
      const file=item?.getAsFile?.();
      if(file){ev.preventDefault();upload(file);}
    });
    $('auto-select').addEventListener('click',()=>{
      if(!state.image)return;
      // Explicit reset: entire screenshot, never an old manual selection.
      state.bounds=null;drawAndInspect();
    });
    $('reset').addEventListener('click',()=>{
      state.image=null;state.bounds=null;state.last=null;
      $('canvas-area').hidden=true;$('result').hidden=true;
      $('file-input').value='';
      if($('scan-scope'))$('scan-scope').textContent='';
      setMessage('Додай новий скриншот графіка.');
    });
    const cv=$('chart-canvas');
    cv.addEventListener('pointerdown',ev=>{
      if(!state.image)return;
      state.drag=pointerPosition(ev);cv.setPointerCapture?.(ev.pointerId);ev.preventDefault();
    });
    cv.addEventListener('pointermove',ev=>{
      if(!state.drag)return;
      const pos=pointerPosition(ev),a=state.drag;
      state.bounds={x:round(Math.min(a.x,pos.x)),y:round(Math.min(a.y,pos.y)),
        w:round(Math.abs(pos.x-a.x)),h:round(Math.abs(pos.y-a.y))};
      draw();
    });
    function release(){
      if(!state.drag)return;
      state.drag=null;
      if(state.bounds?.w<75||state.bounds?.h<65)state.bounds=null;
      drawAndInspect();
    }
    cv.addEventListener('pointerup',release);
    cv.addEventListener('pointercancel',release);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();
