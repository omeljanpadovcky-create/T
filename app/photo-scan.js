/* Offline candlestick-color scanner.
 * Heuristic image processing ONLY: no AI, OCR, price recognition, trade signal,
 * broker execution, remote upload, model calls, or invented predictions.
 */
(() => {
  'use strict';
  // Pixel geometry, never AI. Optional user-picked colors adapt to unusual chart palettes.
  function hsv(r,g,b) {
    const max=Math.max(r,g,b)/255,min=Math.min(r,g,b)/255,delta=max-min,s=max?delta/max:0;
    if(!delta)return {h:0,s,v:max};
    let h;
    if(max===r/255)h=60*(((g-b)/255/delta)%6);
    else if(max===g/255)h=60*((b-r)/255/delta+2);
    else h=60*((r-g)/255/delta+4);
    return {h:(h+360)%360,s,v:max};
  }
  function classify(r,g,b,a,options={}){
    if(a<160)return 0;
    const pixel=hsv(r,g,b);if(pixel.v<.18)return 0;
    const colors=options.colors||{};
    for(const type of [1,2]){
      const ref=colors[type];if(!ref)continue;
      if(ref.s<.16 && pixel.s<.18 && pixel.v>.38 && Math.abs(pixel.v-ref.v)<.12)return type;
      const dh=Math.min(Math.abs(pixel.h-ref.h),360-Math.abs(pixel.h-ref.h));
      if(ref.s>=.16 && pixel.s>=Math.max(.16,ref.s*.45) && dh<=22 && Math.abs(pixel.v-ref.v)<.62)return type;
    }
    // Once both candle colors are manually selected, ignore third-party indicators.
    if(colors[1]&&colors[2])return 0;
    if(pixel.s<.22||pixel.v<.29)return 0;
    if(!colors[1]&&pixel.h>=49&&pixel.h<=197)return 1;
    if(!colors[2]&&(pixel.h<=43||pixel.h>=326))return 2;
    return 0;
  }
  function median(xs){
    if(!xs.length)return null;
    const a=xs.slice().sort((p,q)=>p-q),mid=a.length>>1;
    return a.length%2?a[mid]:(a[mid-1]+a[mid])/2;
  }
  function mergeX(items,width){
    const sorted=items.sort((a,b)=>a.x-b.x||b.area-a.area),out=[],distance=Math.max(2,Math.min(4,Math.round(width*.004)));
    for(const item of sorted){
      const previous=out[out.length-1];
      if(previous&&item.x-previous.x<=distance){if(item.area>previous.area)out[out.length-1]=item;}
      else out.push(item);
    }
    return out;
  }
  function components(mask,w,h){
    const n=w*h,seen=new Uint8Array(n),q=new Int32Array(n),items=[];
    const maxW=Math.max(12,Math.floor(w*.055)),minH=Math.max(3,Math.floor(h*.01));
    for(let p=0;p<n;p++){
      const color=mask[p];if(!color||seen[p])continue;
      q[0]=p;seen[p]=1;
      let head=0,tail=1,area=0,left=w,right=0,top=h,bottom=0;
      while(head<tail){
        const i=q[head++],x=i%w,y=(i/w)|0;area++;
        if(x<left)left=x;if(x>right)right=x;if(y<top)top=y;if(y>bottom)bottom=y;
        if(x>0&&!seen[i-1]&&mask[i-1]===color){seen[i-1]=1;q[tail++]=i-1;}
        if(x+1<w&&!seen[i+1]&&mask[i+1]===color){seen[i+1]=1;q[tail++]=i+1;}
        if(y>0&&!seen[i-w]&&mask[i-w]===color){seen[i-w]=1;q[tail++]=i-w;}
        if(y+1<h&&!seen[i+w]&&mask[i+w]===color){seen[i+w]=1;q[tail++]=i+w;}
      }
      const bw=right-left+1,bh=bottom-top+1;
      if(area<4||bw>maxW||bh<minH||bh>h*.68||bh<bw*.48||area<Math.max(4,.11*bw*bh))continue;
      items.push({color,x:(left+right)/2,y:(top+bottom)/2,minX:left,maxX:right,minY:top,maxY:bottom,area});
    }
    return mergeX(items,w);
  }
  function projections(mask,w,h){
    // Vertical-run fallback: handles narrow wicks/body gaps from JPEG compression.
    const runs=new Array(w).fill(null),minLen=Math.max(4,Math.floor(h*.011));
    for(let x=0;x<w;x++){
      let best=null;
      for(const color of [1,2]){
        let from=-1,longest=0,at=0;
        for(let y=0;y<=h;y++){
          const active=y<h&&mask[y*w+x]===color;
          if(active&&from<0)from=y;
          if(!active&&from>=0){const length=y-from;if(length>longest){longest=length;at=from;}from=-1;}
        }
        if(longest>=minLen&&longest<h*.64&&(!best||longest>best.length)){
          best={color,start:at,end:at+longest-1,length:longest};
        }
      }
      runs[x]=best;
    }
    const out=[];
    for(let x=0;x<w;){
      if(!runs[x]){x++;continue;}
      const first=x,color=runs[x].color;
      let top=h,bottom=0,area=0;
      while(x<w&&runs[x]&&runs[x].color===color){
        top=Math.min(top,runs[x].start);bottom=Math.max(bottom,runs[x].end);
        area+=runs[x].length;x++;
      }
      const bw=x-first,bh=bottom-top+1;
      if(bw<=Math.max(10,w*.047)&&bh>=minLen&&bh<h*.68)
        out.push({color,x:(first+x-1)/2,y:(top+bottom)/2,
          minX:first,maxX:x-1,minY:top,maxY:bottom,area});
    }
    return mergeX(out,w);
  }
  function distribution(items,w){
    if(items.length<2)return {spread:0,bins:0};
    return {
      spread:items[items.length-1].x-items[0].x,
      bins:new Set(items.map(x=>Math.min(4,Math.floor(x.x/Math.max(1,w/5))))).size
    };
  }
  // Group vertically shaped colored components by horizontal proximity.
  // On Bybit screenshots, order-book digits form a separate narrow group,
  // whereas genuine candle bodies span much of the chart width.
  function findChartBounds(imageData,options={}){
    const w=imageData.width,h=imageData.height,d=imageData.data;
    if(w<140||h<120||!d||d.length<w*h*4)return null;
    const mask=new Uint8Array(w*h);
    for(let i=0,j=0;i<mask.length;i++,j+=4)
      mask[i]=classify(d[j],d[j+1],d[j+2],d[j+3],options);
    const items=components(mask,w,h);
    for(const [lo,hi] of [[.31,.91],[.18,.94]]){
      const relevant=items.filter(p=>p.x>=w*.035&&p.x<=w*.94 && p.y>=h*lo&&p.y<=h*hi)
        .sort((a,b)=>a.x-b.x);
      const groups=[];let previous=-Infinity;
      for(const item of relevant){
        if(!groups.length||item.x-previous>Math.max(16,w*.032))groups.push([]);
        groups[groups.length-1].push(item);previous=item.x;
      }
      const best=groups.map(group=>{
        const span=group.length?group[group.length-1].maxX-group[0].minX:0;
        return {group,span,score:group.length*span/w};
      }).filter(v=>v.group.length>=12&&v.span>=w*.24)
        .sort((a,b)=>b.score-a.score)[0];
      if(!best)continue;
      const group=best.group;
      const ymin=Math.min(...group.map(v=>v.minY)),ymax=Math.max(...group.map(v=>v.maxY));
      const left=Math.max(0,Math.floor(group[0].minX-w*.015));
      const right=Math.min(w,Math.ceil(group[group.length-1].maxX+w*.018));
      let top=Math.max(0,Math.floor(Math.max(h*lo+h*.005,ymin-h*.02)));
      let bottom=Math.min(h,Math.ceil(Math.min(h*.94,ymax+h*.055)));
      // Sideways candles occupy a narrow vertical band: give them a real ROI.
      if(bottom-top<h*.24){
        const middle=(top+bottom)/2;
        top=Math.max(0,Math.floor(middle-h*.14));
        bottom=Math.min(h,Math.ceil(middle+h*.14));
      }
      if(right-left<w*.22||bottom-top<h*.19)continue;
      return {x:left,y:top,w:right-left,h:bottom-top,candidates:group.length,auto:true};
    }
    return null;
  }
  function analyzePixels(imageData,options={}){
    const w=imageData.width,h=imageData.height,d=imageData.data;
    if(w<80||h<70||!d||d.length<w*h*4)return {recognized:false,reason:'Область графіка надто мала.'};
    const n=w*h,mask=new Uint8Array(n);
    for(let i=0,j=0;i<n;i++,j+=4)mask[i]=classify(d[j],d[j+1],d[j+2],d[j+3],options);
    const cc=components(mask,w,h),cols=projections(mask,w,h),a=distribution(cc,w),b=distribution(cols,w);
    const columnMode=(cols.length>=cc.length+2&&b.spread>=Math.max(w*.16,a.spread*.75)&&b.bins>=2) ||
      (cc.length<5&&cols.length>cc.length);
    const found=columnMode?cols:cc,disp=columnMode?b:a;
    if(found.length<5||disp.spread<w*.16||disp.bins<2){
      return {recognized:false,candidates:found.length,componentCandidates:cc.length,
        columnCandidates:cols.length,
        reason:'Надто мало розподілених по горизонталі вертикальних елементів. Можливо, це лінійний графік або нестандартні кольори свічок. Обведи лише поле графіка й спробуй вручну вибрати кольори свічок.'};
    }
    const partial=found.length<9||disp.spread<w*.33||disp.bins<3;
    const amount=Math.max(2,Math.floor(found.length/3));
    const edge=Math.max(3,Math.min(12,Math.floor(found.length*.18)));
    const first=found.slice(0,amount),last=found.slice(-amount);
    const firstY=median(first.map(x=>x.y)),lastY=median(last.map(x=>x.y));
    const edgeFirst=median(found.slice(0,edge).map(x=>x.y));
    const edgeLast=median(found.slice(-edge).map(x=>x.y));
    const range=Math.max(...found.map(x=>x.maxY))-Math.min(...found.map(x=>x.minY));
    const globalDrift=(firstY-lastY)/Math.max(1,range);
    const edgeDrift=(edgeFirst-edgeLast)/Math.max(1,range);
    const drift=.65*edgeDrift+.35*globalDrift;
    // Only describe visible, historical displacement. Requiring agreement
    // of both edge and broad samples avoids a false direction from a noisy UI.
    const consistent=Math.sign(edgeDrift)===Math.sign(globalDrift) &&
      Math.abs(edgeDrift)>.16 && Math.abs(drift)>.13;
    const visualDirection=partial||!consistent?'unknown':drift>0?'up':'down';
    const observedDirection=partial?'Недостатньо елементів для оцінки переміщення':
      visualDirection==='up'?'Пізніші елементи вище попередніх (лише зображення)':
      visualDirection==='down'?'Пізніші елементи нижче попередніх (лише зображення)':
      'Без виразної зміни положення елементів (лише зображення)';
    return {recognized:true,partial,visualDirection,candidates:found.length,
      componentCandidates:cc.length,columnCandidates:cols.length,method:columnMode?'column':'regions',
      green:last.filter(x=>x.color===1).length,red:last.filter(x=>x.color===2).length,sample:last.length,
      observedDirection,xSpreadRatio:disp.spread/w,globalDrift,edgeDrift,
      shapes:found.slice(-130).map(x=>({x:x.minX,y:x.minY,w:x.maxX-x.minX+1,h:x.maxY-x.minY+1,color:x.color}))};
  }
  function colorAt(canvas,x,y){
    const ctx=canvas.getContext('2d',{willReadFrequently:true});
    if(!ctx)return null;
    const at=ctx.getImageData(Math.max(0,Math.min(canvas.width-1,Math.round(x))),
      Math.max(0,Math.min(canvas.height-1,Math.round(y))),1,1).data;
    return {hsv:hsv(at[0],at[1],at[2]),css:'rgb('+at[0]+','+at[1]+','+at[2]+')'};
  }
  function attach({image,container,fileName}) {
    if(!image || !container) return;
    const section=document.createElement('section');
    section.className='offline-photo-scanner';
    section.style.cssText='padding:14px;margin:12px 0;border:1px solid #8ea7c1;border-radius:14px;overflow:hidden';
    const title=document.createElement('h3');
    title.textContent='🔬 Що вже відбулося на фото';
    title.style.margin='0 0 8px';
    const explain=document.createElement('p');
    explain.className='report-notice';
    explain.textContent='Це тільки РЕТРОСПЕКТИВА фото: сканер порівнює положення намальованих свічок. Не знає часу знімка й не може сказати, куди піде ціна далі. Для окремого актуального сценарію використовуй перевірку Bybit вище.';
    const canvas=document.createElement('canvas');
    canvas.style.cssText='display:block;max-width:100%;width:100%;height:auto;border-radius:8px;border:1px solid #8194aa;touch-action:none;cursor:crosshair';
    canvas.setAttribute('role','img');
    canvas.setAttribute('aria-label','Фото графіка: перетягни рамку, щоб виділити область сканування');
    const ratio=Math.min(1,800/image.naturalWidth,500/image.naturalHeight);
    canvas.width=Math.max(1,Math.floor(image.naturalWidth*ratio));
    canvas.height=Math.max(1,Math.floor(image.naturalHeight*ratio));
    const w=canvas.width,h=canvas.height,ctx=canvas.getContext('2d');
    const source=document.createElement('canvas');
    source.width=w;source.height=h;
    source.getContext('2d').drawImage(image,0,0,w,h); // picker samples unmasked source, never overlay
    const colors={};
    let picking=0,color1=null,color2=null;
    const fallbackCrop=()=>({x:Math.floor(w*.08),y:Math.floor(h*.13),
      w:Math.floor(w*.83),h:Math.floor(h*.72)});
    const detectCrop=()=>findChartBounds(source.getContext('2d',{willReadFrequently:true})
      .getImageData(0,0,w,h),{colors})||fallbackCrop();
    let crop=detectCrop(),userCrop=false;
    let origin=null,dragging=false,lastShapes=[];
    function draw(){
      ctx.clearRect(0,0,w,h);
      ctx.drawImage(image,0,0,w,h);
      ctx.fillStyle='rgba(0,0,0,.38)';
      ctx.fillRect(0,0,w,crop.y);
      ctx.fillRect(0,crop.y,crop.x,crop.h);
      ctx.fillRect(crop.x+crop.w,crop.y,w-crop.x-crop.w,crop.h);
      ctx.fillRect(0,crop.y+crop.h,w,h-crop.y-crop.h);
      ctx.lineWidth=2;
      ctx.strokeStyle='#f7cb53';
      ctx.setLineDash([8,5]);
      ctx.strokeRect(crop.x+1,crop.y+1,Math.max(0,crop.w-2),Math.max(0,crop.h-2));
      ctx.setLineDash([]);
      if(lastShapes.length){
        ctx.lineWidth=1.5;
        for(const s of lastShapes){
          ctx.strokeStyle=s.color===1?'#00ff9a':'#ff5353';
          ctx.strokeRect(crop.x+s.x,crop.y+s.y,s.w,s.h);
        }
      }
    }
    function where(event){
      const rect=canvas.getBoundingClientRect();
      return {
        x:Math.min(w,Math.max(0,(event.clientX-rect.left)*(w/rect.width))),
        y:Math.min(h,Math.max(0,(event.clientY-rect.top)*(h/rect.height)))
      };
    }
    canvas.addEventListener('pointerdown',e=>{
      if(e.button!==0 && e.pointerType==='mouse')return;
      if(picking){
        const sampled=colorAt(source,where(e).x,where(e).y);
        if(sampled){
          colors[picking]=sampled.hsv;
          const selected=picking;
          picking=0;
          if(selected===1 && color1){color1.textContent='✓ Колір 1 вибрано';color1.style.borderColor=sampled.css;}
          if(selected===2 && color2){color2.textContent='✓ Колір 2 вибрано';color2.style.borderColor=sampled.css;}
          out.textContent='Палітру оновлено, виконуємо сканування за вибраним кольором…';
          if(!userCrop){crop=detectCrop();lastShapes=[];draw();}
          scan();
        }
        return;
      }
      origin=where(e);dragging=true;lastShapes=[];
      canvas.setPointerCapture?.(e.pointerId);
      crop={x:origin.x,y:origin.y,w:1,h:1};draw();
    });
    canvas.addEventListener('pointermove',e=>{
      if(!dragging||!origin)return;
      const at=where(e);
      crop={x:Math.min(at.x,origin.x),y:Math.min(at.y,origin.y),
        w:Math.abs(at.x-origin.x),h:Math.abs(at.y-origin.y)};
      draw();
    });
    canvas.addEventListener('pointerup',e=>{
      if(!dragging)return;
      dragging=false;const at=where(e);
      const next={x:Math.min(at.x,origin.x),y:Math.min(at.y,origin.y),
        w:Math.abs(at.x-origin.x),h:Math.abs(at.y-origin.y)};
      if(next.w>50 && next.h>45){crop=next;userCrop=true;}
      else {crop=detectCrop();userCrop=false;}
      lastShapes=[];draw();
    });
    canvas.addEventListener('pointercancel',()=>{dragging=false;origin=null;draw();});
    const actions=document.createElement('div');
    actions.style.cssText='display:flex;flex-wrap:wrap;gap:8px;margin:10px 0';
    const button=document.createElement('button');button.type='button';button.className='small-button';
    button.textContent='🔎 Сканувати вибрану область';
    const reset=document.createElement('button');reset.type='button';reset.className='small-button';
    reset.textContent='↺ Знайти графік автоматично';
    color1=document.createElement('button');color1.type='button';color1.className='small-button';
    color1.textContent='🎨 Вибрати колір 1 (зелений)';
    color2=document.createElement('button');color2.type='button';color2.className='small-button';
    color2.textContent='🎨 Вибрати колір 2 (червоний)';
    const autoColors=document.createElement('button');autoColors.type='button';autoColors.className='small-button';
    autoColors.textContent='↺ Автопалітра';
    color1.addEventListener('click',()=>{picking=1;out.textContent='Клацни по ТІЛУ зеленої (або першої кольорової) свічки на зображенні.';});
    color2.addEventListener('click',()=>{picking=2;out.textContent='Клацни по ТІЛУ червоної (або другої кольорової) свічки на зображенні.';});
    autoColors.addEventListener('click',()=>{
      delete colors[1];delete colors[2];picking=0;
      color1.textContent='🎨 Вибрати колір 1 (зелений)';color1.style.borderColor='';
      color2.textContent='🎨 Вибрати колір 2 (червоний)';color2.style.borderColor='';
      if(!userCrop){crop=detectCrop();lastShapes=[];draw();}
      scan();
    });
    const out=document.createElement('div');
    out.setAttribute('role','status');out.setAttribute('aria-live','polite');
    out.style.cssText='font-size:13px;line-height:1.55;overflow-wrap:anywhere';
    function showVerdict(direction,details){
      // Only report observed movement when the pixel evidence passes quality checks.
      const labels={up:'НА ФОТО: ↑ РІСТ',down:'НА ФОТО: ↓ СПАД',unknown:'НА ФОТО: НЕВИЗНАЧЕНО'};
      const label=document.createElement('div');
      label.textContent=labels[direction]||labels.unknown;
      label.style.cssText='font-size:clamp(20px,4vw,31px);font-weight:750;letter-spacing:.01em;line-height:1.3;margin:8px 0;';
      label.style.color='inherit';
      const qualifier=document.createElement('div');
      qualifier.className='report-notice';
      qualifier.textContent=direction==='unknown'?
        'Для висновку бракує надійно розпізнаних свічок. Напрям не вгадуємо.':
        'ЛИШЕ вже намальований рух на цьому зображенні. До наступної свічки висновок не має стосунку.';
      const technical=document.createElement('details');
      technical.style.marginTop='10px';
      const summary=document.createElement('summary');
      summary.textContent='Деталі розпізнавання';
      const description=document.createElement('p');
      description.style.whiteSpace='pre-wrap';
      description.textContent=details||'';
      technical.append(summary,description);
      out.replaceChildren(label,qualifier,technical);
    }
    reset.addEventListener('click',()=>{
      userCrop=false;crop=detectCrop();lastShapes=[];draw();scan();
    });
    function scan(){
      if(crop.w<50||crop.h<45){showVerdict('unknown','Збільш виділену область графіка.');return;}
      const sw=Math.max(1,Math.floor(crop.w)),sh=Math.max(1,Math.floor(crop.h));
      const tmp=document.createElement('canvas');tmp.width=sw;tmp.height=sh;
      const tctx=tmp.getContext('2d',{willReadFrequently:true});
      if(!tctx){showVerdict('unknown','Canvas недоступний у браузері.');return;}
      tctx.drawImage(image,crop.x/w*image.naturalWidth,crop.y/h*image.naturalHeight,
        crop.w/w*image.naturalWidth,crop.h/h*image.naturalHeight,0,0,sw,sh);
      let report;
      try{report=analyzePixels(tctx.getImageData(0,0,sw,sh),{colors});}
      catch(e){showVerdict('unknown','Не вдалося прочитати пікселі цього зображення.');return;}
      if(!report.recognized){
        lastShapes=[];draw();
        showVerdict('unknown',report.reason+
          (report.candidates===undefined?'':'\nКандидатів на свічки: '+report.candidates)+
          '\nФото залишається лише у твоєму браузері.');
        return;
      }
      lastShapes=report.shapes;draw();
      showVerdict(report.visualDirection||'unknown',
        'Можливих вертикальних елементів: '+report.candidates+' (показані рамки).\n'+
        'Остання третина: колір 1 — '+report.green+', колір 2 — '+report.red+'.\n'+
        'Розташування: '+report.observedDirection+'.\n'+
        (report.partial?'Мало даних: це лише часткове розпізнавання.\n':'')+'\n'+
        'Це лише геометрія кольорових фігур. Індикатори або текст можуть бути помилково прийняті за свічки. Висновок НЕ означає рух ціни в майбутньому. BUY/SELL: невідомо.\n'+
        'Зображення не відправлялося на сервер.');
    }
    button.addEventListener('click',scan);
    actions.append(button,reset,color1,color2,autoColors);
    const autodetect=document.createElement('small');
    if(crop.auto)autodetect.textContent='✓ Графік відокремлено від меню та книги ордерів автоматично.';
    else autodetect.textContent='⚪ Автовиділення не вдалося. Обведи поле графіка вручну.';
    section.append(title,explain,autodetect,canvas,actions,out);
    container.appendChild(section);
    draw();
    // Preview already decoded; this is a local, synchronous scan, not a background job.
    scan();
  }
  window.cryptoMyshkaPhotoScan={attach,analyzePixels,findChartBounds};
})();
