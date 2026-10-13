/* Crypto Myshka: minimal, keyless screenshot explanation.
 * All calculations describe visible pixels, not a future trade or verified prices.
 */
(() => {
  'use strict';
  const $=id=>document.getElementById(id);
  const scanner=()=>window.cryptoMyshkaPhotoScan;
  const state={image:null,filename:'',bounds:null,width:0,height:0,drag:null,canvas:null,last:null};
  const round=n=>Number.isFinite(n)?Math.round(n):0;
  function setMessage(message){$('message').textContent=message;}
  function showReport(title,paragraph,stats=[],facts=[],warning=''){
    const result=$('result');result.hidden=false;
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
  function fitBounds(){
    const canvas=state.canvas;
    if(!canvas)return null;
    const candidate=scanner()?.findChartBounds?.(
      canvas.getContext('2d',{willReadFrequently:true})
        .getImageData(0,0,canvas.width,canvas.height));
    const fallback={x:round(canvas.width*.08),y:round(canvas.height*.10),
      w:round(canvas.width*.79),h:round(canvas.height*.77)};
    return candidate&&candidate.w>=80&&candidate.h>=70?candidate:fallback;
  }
  function draw(){
    const canvas=state.canvas,img=state.image;
    if(!canvas||!img)return;
    const ctx=canvas.getContext('2d');
    ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.drawImage(img,0,0,canvas.width,canvas.height);
    const b=state.bounds;
    if(!b)return;
    ctx.fillStyle='rgba(4,11,24,.50)';
    ctx.fillRect(0,0,canvas.width,b.y);
    ctx.fillRect(0,b.y,b.x,b.h);
    ctx.fillRect(b.x+b.w,b.y,canvas.width-b.x-b.w,b.h);
    ctx.fillRect(0,b.y+b.h,canvas.width,canvas.height-b.y-b.h);
    ctx.strokeStyle='#f6d17a';ctx.lineWidth=3;ctx.setLineDash([9,6]);
    ctx.strokeRect(b.x,b.y,b.w,b.h);ctx.setLineDash([]);
  }
  function inspect(){
    if(!state.image||!state.bounds)return;
    const b=state.bounds,c=state.canvas;
    const source=document.createElement('canvas');
    source.width=Math.max(1,round(b.w));source.height=Math.max(1,round(b.h));
    const sx=b.x/c.width*state.image.naturalWidth;
    const sy=b.y/c.height*state.image.naturalHeight;
    const sw=b.w/c.width*state.image.naturalWidth;
    const sh=b.h/c.height*state.image.naturalHeight;
    const ctx=source.getContext('2d',{willReadFrequently:true});
    ctx.drawImage(state.image,sx,sy,sw,sh,0,0,source.width,source.height);
    const pixels=ctx.getImageData(0,0,source.width,source.height);
    const report=scanner()?.analyzePixels?.(pixels);
    state.last=report||null;
    if(!report?.recognized){
      showReport('Недостатньо даних',
        'Мишка не змогла надійно знайти свічки в цій області.',
        [],[report?.reason||'Виділи лише поле з червоними й зеленими свічками.',
          'Спробуй прибрати з рамки кнопки, цифри, меню й графіки індикаторів.']);
      setMessage('Фото прочитано, але свічки не розпізнано. Зміни рамку.');
      return;
    }
    const green=Math.max(0,Number(report.green)||0);
    const red=Math.max(0,Number(report.red)||0);
    const observed=green+red;
    const greenPct=observed>0?100*green/observed:null;
    const redPct=observed>0?100*red/observed:null;
    const trend=report.reliable===true?
      report.trendState||report.visualDirection:'unreliable';
    const title=trend==='up'?'На фото видно зростання':
      trend==='down'?'На фото видно падіння':
      trend==='sideways'?'Графік рухається боком':
      trend==='mixed'?'На графіку суперечливий рух':'Чіткий тренд не визначено';
    let explanation='';
    if(trend==='up')explanation='Правіші свічки розташовані вище за ліві. Це візуальна ознака вже відбулого зростання, але не доказ наступного руху.';
    else if(trend==='down')explanation='Правіші свічки розташовані нижче за ліві. Це візуальна ознака вже відбулого падіння, але не доказ наступного руху.';
    else if(trend==='sideways')explanation='Положення ранніх і пізніх свічок змінюється незначно: виразного висхідного чи спадного тренду немає.';
    else if(trend==='mixed')explanation='Різні ділянки скриншота показують протилежний рух, тому стверджувати, що ціна впевнено йде вгору або вниз, не можна.';
    else explanation='Свічкоподібні контури розпізнано, проте даних замало для надійного визначення напрямку.';
    const stats=[
      {value:String(round(report.candidates||0)),label:'знайдено контурів'},
      {value:greenPct===null?'—':round(greenPct)+'%',label:'зелених в останній вибірці'},
      {value:redPct===null?'—':round(redPct)+'%',label:'червоних в останній вибірці'}
    ];
    const facts=[
      'З останньої вибірки: зелених '+round(green)+', червоних '+round(red)+'.',
      'M1 означає, що кожна свічка охоплює одну хвилину; скриншот не показує результат наступних 60 секунд.',
      'Колір свічок показує перевагу певного типу свічок у вибірці, а не ймовірність наступного результату.',
      'Напрям оцінений за розташуванням свічкоподібних контурів зліва направо: '+String(report.observedDirection||'невідомий')+'.'
    ];
    const quality=Number(report.qualityScore);
    if(Number.isFinite(quality))facts.push('Якість виявлення контурів '+round(quality)+'/100 — це НЕ точність прогнозування.');
    showReport(title,explanation,stats,facts,
      'Відсотки вище — частка кольорів свічок, НЕ зміна ціни, НЕ ймовірність BUY/SELL і НЕ очікуваний прибуток. Для реальної відсоткової зміни ціни потрібні числові ціни початку й кінця періоду. Даних майбутньої експірації скриншот не містить.');
    setMessage('Готово. Мишка описала минулі свічки M1; результат наступної хвилини залишається невідомим.');
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
        const ctx=canvas.getContext('2d',{willReadFrequently:true});
        ctx.drawImage(image,0,0,canvas.width,canvas.height);
        state.bounds=fitBounds();
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
      const ctx=state.canvas.getContext('2d',{willReadFrequently:true});
      ctx.clearRect(0,0,state.canvas.width,state.canvas.height);
      ctx.drawImage(state.image,0,0,state.canvas.width,state.canvas.height);
      state.bounds=fitBounds();drawAndInspect();
    });
    $('reset').addEventListener('click',()=>{
      state.image=null;state.bounds=null;state.last=null;
      $('canvas-area').hidden=true;$('result').hidden=true;
      $('file-input').value='';setMessage('Додай новий скриншот графіка.');
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
      if(state.bounds?.w<75||state.bounds?.h<65){
        state.bounds={x:round(state.canvas.width*.08),y:round(state.canvas.height*.10),
          w:round(state.canvas.width*.79),h:round(state.canvas.height*.77)};
      }
      drawAndInspect();
    }
    cv.addEventListener('pointerup',release);
    cv.addEventListener('pointercancel',release);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();
