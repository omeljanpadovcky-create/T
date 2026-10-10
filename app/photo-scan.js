/* Offline candlestick-color scanner.
 * Heuristic image processing ONLY: no AI, OCR, price recognition, trade signal,
 * broker execution, remote upload, model calls, or invented predictions.
 */
(() => {
  'use strict';
  function classify(r,g,b,a) {
    if (a < 180) return 0;
    const hi=Math.max(r,g,b), lo=Math.min(r,g,b), delta=hi-lo;
    if (hi < 75 || delta < 50 || delta/hi < 0.35) return 0;
    let hue=0;
    if (hi===r) hue=60*(((g-b)/delta)%6);
    else if (hi===g) hue=60*((b-r)/delta+2);
    else hue=60*((r-g)/delta+4);
    if(hue<0)hue+=360;
    if(hue>=67 && hue<=187) return 1;  // green/mint bullish candles
    if(hue<=23 || hue>=336) return 2;    // red bearish candles
    return 0;
  }
  function median(values) {
    if(!values.length) return null;
    const s=values.slice().sort((a,b)=>a-b),m=Math.floor(s.length/2);
    return s.length%2?s[m]:(s[m-1]+s[m])/2;
  }
  function analyzePixels(imageData) {
    const width=imageData.width,height=imageData.height,data=imageData.data;
    if(width<80||height<70||!data||data.length<width*height*4)
      return {recognized:false,reason:'Область графіка замала для аналізу.'};
    const n=width*height, mask=new Uint8Array(n),seen=new Uint8Array(n);
    for(let i=0,j=0;i<n;i++,j+=4)mask[i]=classify(data[j],data[j+1],data[j+2],data[j+3]);
    const queue=new Int32Array(n), candidates=[];
    const maxWidth=Math.max(13,Math.floor(width*0.05));
    const minHeight=Math.max(5,Math.floor(height*0.016));
    for(let pos=0;pos<n;pos++){
      const color=mask[pos];
      if(!color||seen[pos])continue;
      let head=0,tail=1,area=0;
      queue[0]=pos;seen[pos]=1;
      let minX=width,maxX=0,minY=height,maxY=0;
      while(head<tail){
        const p=queue[head++],x=p%width,y=(p/width)|0;
        area++;
        if(x<minX)minX=x;if(x>maxX)maxX=x;
        if(y<minY)minY=y;if(y>maxY)maxY=y;
        const neighbors=[x? p-1:-1,x+1<width?p+1:-1,y?p-width:-1,y+1<height?p+width:-1];
        for(let k=0;k<4;k++){
          const q=neighbors[k];
          if(q>=0 && !seen[q] && mask[q]===color){seen[q]=1;queue[tail++]=q;}
        }
      }
      const bw=maxX-minX+1,bh=maxY-minY+1;
      if(area<6 || bw>maxWidth || bh<minHeight || bh>height*0.72 || bh<bw*0.54)continue;
      // Discard isolated tiny specks, long horizontal text or chart decorations.
      if(area < Math.max(6,0.15*bw*bh))continue;
      candidates.push({color,x:(minX+maxX)/2,y:(minY+maxY)/2,minX,maxX,minY,maxY,area});
    }
    candidates.sort((a,b)=>a.x-b.x||b.area-a.area);
    const distinct=[];
    for(const candidate of candidates){
      const prev=distinct[distinct.length-1];
      if(prev && candidate.x-prev.x<Math.max(3,width*0.004)){
        if(candidate.area>prev.area)distinct[distinct.length-1]=candidate;
      }else distinct.push(candidate);
    }
    const spread=distinct.length>1?distinct[distinct.length-1].x-distinct[0].x:0;
    const bins=new Set(distinct.map(x=>Math.floor(x.x/Math.max(1,width/5))));
    if(distinct.length<8 || spread<width*0.26 || bins.size<3){
      return {
        recognized:false,candidates:distinct.length,
        reason:'Кольорові свічки не вдалося достатньо надійно відрізнити від тексту, ліній або кнопок. Виділи саме поле графіка (без меню), потім повтори.'
      };
    }
    const size=Math.max(3,Math.floor(distinct.length/3));
    const first=distinct.slice(0,size),last=distinct.slice(-size);
    const firstY=median(first.map(x=>x.y)),lastY=median(last.map(x=>x.y));
    const fullRange=Math.max(...distinct.map(x=>x.maxY))-Math.min(...distinct.map(x=>x.minY));
    const drift=(firstY-lastY)/Math.max(1,fullRange);
    const observedDirection=drift>0.12?'Вищі позиції свічок праворуч':drift< -0.12?
      'Нижчі позиції свічок праворуч':'Без виразної зміни вертикальної позиції';
    const greens=last.filter(x=>x.color===1).length;
    const reds=last.length-greens;
    return {
      recognized:true, candidates:distinct.length, firstY,lastY,drift,
      green:greens,red:reds,sample:last.length,observedDirection,
      xSpreadRatio:spread/width,
      shapes:distinct.slice(-120).map(x=>({x:x.minX,y:x.minY,w:x.maxX-x.minX+1,h:x.maxY-x.minY+1,color:x.color}))
    };
  }
  function attach({image,container,fileName}) {
    if(!image || !container) return;
    const section=document.createElement('section');
    section.className='offline-photo-scanner';
    section.style.cssText='padding:14px;margin:12px 0;border:1px solid #8ea7c1;border-radius:14px;overflow:hidden';
    const title=document.createElement('h3');
    title.textContent='🔬 Сканер фото — без AI-ключа';
    title.style.margin='0 0 8px';
    const explain=document.createElement('p');
    explain.className='report-notice';
    explain.textContent='Працює локально в браузері навіть при HTTP 402. Визначає лише можливі червоні/зелені свічки та їхнє розташування. Не розпізнає ціни, таймфрейм, назву активу або майбутній напрям. Пальцем чи мишею обведи саме графік без меню та підписів.';
    const canvas=document.createElement('canvas');
    canvas.style.cssText='display:block;max-width:100%;width:100%;height:auto;border-radius:8px;border:1px solid #8194aa;touch-action:none;cursor:crosshair';
    canvas.setAttribute('role','img');
    canvas.setAttribute('aria-label','Фото графіка: перетягни рамку, щоб виділити область сканування');
    const ratio=Math.min(1,800/image.naturalWidth,500/image.naturalHeight);
    canvas.width=Math.max(1,Math.floor(image.naturalWidth*ratio));
    canvas.height=Math.max(1,Math.floor(image.naturalHeight*ratio));
    const w=canvas.width,h=canvas.height,ctx=canvas.getContext('2d');
    let crop={x:Math.floor(w*0.08),y:Math.floor(h*0.13),w:Math.floor(w*0.83),h:Math.floor(h*0.72)};
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
      if(next.w>50 && next.h>45)crop=next;
      else crop={x:Math.floor(w*0.08),y:Math.floor(h*0.13),w:Math.floor(w*0.83),h:Math.floor(h*0.72)};
      lastShapes=[];draw();
    });
    canvas.addEventListener('pointercancel',()=>{dragging=false;origin=null;draw();});
    const actions=document.createElement('div');
    actions.style.cssText='display:flex;flex-wrap:wrap;gap:8px;margin:10px 0';
    const button=document.createElement('button');button.type='button';button.className='small-button';
    button.textContent='🔎 Сканувати вибрану область';
    const reset=document.createElement('button');reset.type='button';reset.className='small-button';
    reset.textContent='↺ Скинути рамку';
    const out=document.createElement('p');
    out.setAttribute('role','status');out.setAttribute('aria-live','polite');
    out.style.cssText='white-space:pre-wrap;font-size:13px;line-height:1.55;overflow-wrap:anywhere';
    reset.addEventListener('click',()=>{
      crop={x:Math.floor(w*0.08),y:Math.floor(h*0.13),w:Math.floor(w*0.83),h:Math.floor(h*0.72)};
      lastShapes=[];draw();out.textContent='Область скинуто. Натисни «Сканувати».';
    });
    function scan(){
      if(crop.w<50||crop.h<45){out.textContent='⚠️ Збільш виділену область графіка.';return;}
      const sw=Math.max(1,Math.floor(crop.w)),sh=Math.max(1,Math.floor(crop.h));
      const tmp=document.createElement('canvas');tmp.width=sw;tmp.height=sh;
      const tctx=tmp.getContext('2d',{willReadFrequently:true});
      if(!tctx){out.textContent='Canvas недоступний у браузері.';return;}
      tctx.drawImage(image,crop.x/w*image.naturalWidth,crop.y/h*image.naturalHeight,
        crop.w/w*image.naturalWidth,crop.h/h*image.naturalHeight,0,0,sw,sh);
      let report;
      try{report=analyzePixels(tctx.getImageData(0,0,sw,sh));}
      catch(e){out.textContent='⚠️ Не вдалося прочитати пікселі цього зображення.';return;}
      if(!report.recognized){
        lastShapes=[];draw();
        out.textContent='⚪ Сканування виконано, але результат НЕВИЗНАЧЕНИЙ.\n'+report.reason+
          (report.candidates===undefined?'':'\nКандидатів на свічки: '+report.candidates)+
          '\nФото залишається лише у твоєму браузері.';
        return;
      }
      lastShapes=report.shapes;draw();
      out.textContent='🟠 ЕКСПЕРИМЕНТАЛЬНЕ РОЗПІЗНАВАННЯ ПІКСЕЛІВ · НЕ AI\n'+
        'Можливих кольорових свічок: '+report.candidates+' (обведено рамками).\n'+
        'Остання третина розпізнаних елементів: зелених '+report.green+', червоних '+report.red+'.\n'+
        'Положення елементів: '+report.observedDirection+'.\n\n'+
        'Це лише геометрія кольорових фігур на вибраному фрагменті. Розпізнавання може помилково прийняти індикатори або текст за свічки. Без підписів осей та незалежних OHLCV НЕ визначаємо ціни, актив чи прогноз. BUY/SELL: НЕВИЗНАЧЕНО.\n'+
        'Зображення не відправлялося на сервер.';
    }
    button.addEventListener('click',scan);
    actions.append(button,reset);
    section.append(title,explain,canvas,actions,out);
    container.appendChild(section);
    draw();
    // Preview already decoded; this is a local, synchronous scan, not a background job.
    scan();
  }
  window.cryptoMyshkaPhotoScan={attach,analyzePixels};
})();
