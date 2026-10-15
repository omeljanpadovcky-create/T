/* Crypto Myshka Price Action v1 — deterministic, read-only analysis.
 * Inspired by the first three Zakulisye Treydera lessons, NOT a copy of a proven
 * strategy. Closed exchange OHLC only; no Martingale, orders or probability claims.
 * UMD: browser global + Node test import.
 */
(function(root,factory){
  const api=factory();
  if(typeof module==='object'&&module.exports)module.exports=api;
  if(root)root.cryptoMyshkaPriceAction=api;
})(typeof window!=='undefined'?window:null,function(){
  'use strict';
  const finite=Number.isFinite;
  const median=xs=>{
    if(!xs.length)return null;
    const a=xs.slice().sort((x,y)=>x-y),i=Math.floor(a.length/2);
    return a.length%2?a[i]:(a[i-1]+a[i])/2;
  };
  function normalize(rows){
    if(!Array.isArray(rows))throw Error('Очікується масив завершених OHLC-свічок.');
    return rows.map((row,i)=>{
      const c={start:Number(row.start),open:Number(row.open),high:Number(row.high),
        low:Number(row.low),close:Number(row.close)};
      if(!Object.values(c).every(finite)||c.start<=0||c.low<=0||c.high<c.low||
         c.high<Math.max(c.open,c.close)||c.low>Math.min(c.open,c.close)||
         c.open<=0||c.close<=0)throw Error('Некоректна OHLC-свічка №'+(i+1)+'.');
      if(i>0&&c.start<=Number(rows[i-1].start))throw Error('Свічки не впорядковані.');
      return c;
    });
  }
  function atr(rows,n=14){
    if(rows.length<n+1)return null;
    let s=0;
    for(let i=rows.length-n;i<rows.length;i++){
      const c=rows[i],prior=rows[i-1];
      s+=Math.max(c.high-c.low,Math.abs(c.high-prior.close),Math.abs(c.low-prior.close));
    }
    return s/n;
  }
  function pivots(rows,k=2){
    const highs=[],lows=[];
    for(let i=k;i<rows.length-k;i++){
      const c=rows[i];
      const h=rows.slice(i-k,i+k+1),a=h.every((r,j)=>j===k||c.high>=r.high) &&
        h.some((r,j)=>j<k&&c.high>r.high);
      const l=h.every((r,j)=>j===k||c.low<=r.low) &&
        h.some((r,j)=>j<k&&c.low<r.low);
      if(a)highs.push({index:i,price:c.high});
      if(l)lows.push({index:i,price:c.low});
    }
    return {highs,lows};
  }
  function level(p,price,a,below){
    const pts=p.filter(x=>below?x.price<=price+a*.18:x.price>=price-a*.18);
    const ordered=pts.slice().sort((x,y)=>Math.abs(x.price-price)-Math.abs(y.price-price));
    for(const seed of ordered){
      const group=pts.filter(x=>Math.abs(x.price-seed.price)<=a*.35);
      if(group.length>=2){
        const value=median(group.map(x=>x.price));
        if(below?value<=price+a*.18:value>=price-a*.18)
          return {price:value,touches:group.length,confirmed:true};
      }
    }
    return null;
  }
  function regression(points){
    const n=points.length,mid=(n-1)/2;
    const my=points.reduce((s,v)=>s+v,0)/n;
    let cov=0,variance=0;
    for(let i=0;i<n;i++){cov+=(i-mid)*(points[i]-my);variance+=(i-mid)**2;}
    return variance?cov/variance:0;
  }
  function pattern(rows,a){
    const x=rows.slice(-24);
    if(x.length<24)return {name:'недостатньо історії',bias:'wait',confirmed:false};
    const hs=regression(x.map(c=>c.high))/a,ls=regression(x.map(c=>c.low))/a;
    const endHigh=Math.max(...x.slice(-6).map(c=>c.high));
    const endLow=Math.min(...x.slice(-6).map(c=>c.low));
    const startHigh=Math.max(...x.slice(0,6).map(c=>c.high));
    const startLow=Math.min(...x.slice(0,6).map(c=>c.low));
    const tightening=(endHigh-endLow)<(startHigh-startLow)*.82;
    const flat=v=>Math.abs(v)<.055,up=v=>v>.075,down=v=>v<-.075;
    const prior=rows.slice(-40,-24);
    const impulse=prior.length===16?(prior[15].close-prior[0].close)/a:0;
    let name='формація нечітка';
    if(flat(hs)&&flat(ls))name='горизонтальний діапазон';
    else if(flat(hs)&&up(ls)&&tightening)name='висхідний трикутник';
    else if(flat(ls)&&down(hs)&&tightening)name='низхідний трикутник';
    else if(tightening&&up(hs)&&up(ls))name='висхідний клин';
    else if(tightening&&down(hs)&&down(ls))name='низхідний клин';
    else if(up(hs)&&up(ls)&&Math.abs(hs-ls)<.16)name='висхідний канал';
    else if(down(hs)&&down(ls)&&Math.abs(hs-ls)<.16)name='низхідний канал';
    if(impulse>2.5&&tightening&&hs<.07&&ls>-.25)
      name='можливий бичачий вимпел (потребує пробою)';
    return {name,bias:'wait',confirmed:name!=='формація нечітка',
      slopes:{high:hs,low:ls},tightening};
  }
  function analyze(input){
    const rows=normalize(input);
    if(rows.length<55)return {bias:'wait',reasons:['Потрібно щонайменше 55 завершених свічок.'],
      trend:'unknown',levels:null,pattern:null,observations:[]};
    const a=atr(rows),last=rows[rows.length-1],previous=rows[rows.length-2];
    if(!(a>0))return {bias:'wait',reasons:['Рух ціни занадто малий для аналізу.'],
      trend:'unknown',levels:null,pattern:null,observations:[]};
    const recent=rows.slice(-75);
    const turns=pivots(recent);
    const p={highs:turns.highs.map(x=>({...x,index:x.index+rows.length-recent.length})),
      lows:turns.lows.map(x=>({...x,index:x.index+rows.length-recent.length}))};
    const s=level(p.lows,last.close,a,true);
    const r=level(p.highs,last.close,a,false);
    const lastHigh=p.highs.slice(-2),lastLow=p.lows.slice(-2);
    const upTrend=lastHigh.length===2&&lastLow.length===2&&
      lastHigh[1].price>lastHigh[0].price+a*.16&&
      lastLow[1].price>lastLow[0].price+a*.16;
    const downTrend=lastHigh.length===2&&lastLow.length===2&&
      lastHigh[1].price<lastHigh[0].price-a*.16&&
      lastLow[1].price<lastLow[0].price-a*.16;
    const trend=upTrend?'up':downTrend?'down':'sideways';
    const body=Math.abs(last.close-last.open);
    const wickLow=Math.min(last.open,last.close)-last.low;
    const wickHigh=last.high-Math.max(last.open,last.close);
    const span=Math.max(last.high-last.low,Number.EPSILON);
    const bullishWick=wickLow>=Math.max(a*.28,body*1.3)&&
      (last.close-last.low)/span>=.62;
    const bearishWick=wickHigh>=Math.max(a*.28,body*1.3)&&
      (last.high-last.close)/span>=.62;
    const nearS=s&&last.close-s.price>=-a*.15&&last.close-s.price<=a*.75;
    const nearR=r&&r.price-last.close>=-a*.15&&r.price-last.close<=a*.75;
    const bullishBounce=!!nearS&&last.close>last.open&&
      last.low<=s.price+a*.35&&last.close>=previous.close-a*.2;
    const bearishBounce=!!nearR&&last.close<last.open&&
      last.high>=r.price-a*.35&&last.close<=previous.close+a*.2;
    const pat=pattern(rows,a);
    // Each vote must be grounded in a separate observable property. Pattern
    // names alone are not votes. Only reversal confirmation near known levels
    // plus consistent market structure yields a directional research scenario.
    const upVotes=[bullishBounce?2:0,upTrend?1:0,bullishWick&&nearS?1:0];
    const downVotes=[bearishBounce?2:0,downTrend?1:0,bearishWick&&nearR?1:0];
    const up=upVotes.reduce((x,y)=>x+y,0),down=downVotes.reduce((x,y)=>x+y,0);
    let bias='wait';
    if(up>=3&&up-down>=2&&bullishBounce)bias='up';
    if(down>=3&&down-up>=2&&bearishBounce)bias='down';
    const reasons=[];
    reasons.push(trend==='up'?'Підтверджені HH/HL (висхідна структура).':
      trend==='down'?'Підтверджені LH/LL (низхідна структура).':
        'Немає послідовного підтвердження HH/HL або LH/LL.');
    reasons.push(s?'Підтримка: '+s.touches+' підтверджених локальних мінімумів.':
      'Надійна підтримка з повторних мінімумів не знайдена.');
    reasons.push(r?'Опір: '+r.touches+' підтверджених локальних максимумів.':
      'Надійний опір із повторних максимумів не знайдений.');
    reasons.push('Формація: '+pat.name+' (опис історії, не доказ пробою).');
    if(bullishBounce)reasons.push('Остання завершена свічка відійшла вгору від підтримки.');
    if(bearishBounce)reasons.push('Остання завершена свічка відійшла вниз від опору.');
    if(bullishWick&&nearS)reasons.push('Нижня тінь свічки свідчить про відхилення нижчих цін.');
    if(bearishWick&&nearR)reasons.push('Верхня тінь свічки свідчить про відхилення вищих цін.');
    if(bias==='wait')reasons.push('Умов підтвердження замало або є суперечність — WAIT.');
    return {bias,trend,levels:{support:s,resistance:r},pattern:pat,
      atr:a,lastClose:last.close,lastStart:last.start,score:{up,down},
      reasons,observations:[{name:'Зелена/червона остання свічка',
        value:last.close>last.open?'зелена':last.close<last.open?'червона':'доджі'}]};
  }
  function backtest(input,opts={}){
    const rows=normalize(input),payout=opts.payout===undefined?.9:Number(opts.payout);
    if(!(payout>0&&payout<=1))throw Error('Виплата повинна бути в межах (0;1].');
    const warmup=80;
    let wins=0,losses=0,ties=0,wait=0,net=0,streak=0,maxLossStreak=0;
    const records=[];
    for(let i=warmup;i<rows.length-1;i++){
      const guess=analyze(rows.slice(0,i+1));
      if(guess.bias==='wait'){wait++;continue;}
      const entry=rows[i].close,exit=rows[i+1].close;
      if(exit===entry){ties++;continue;}
      const won=(exit>entry)===(guess.bias==='up');
      if(won){wins++;streak=0;net+=payout;}else{losses++;streak++;net-=1;}
      maxLossStreak=Math.max(maxLossStreak,streak);
      records.push({start:rows[i].start,bias:guess.bias,entry,exit,won});
    }
    const trades=wins+losses;
    // Accuracy only displayed after at least 30 evaluated, non-tie scenarios.
    return {payout,trades,wins,losses,ties,wait,netUnits:net,
      accuracy:trades>=30?100*wins/trades:null,rawAccuracy:trades?100*wins/trades:null,
      maxLossStreak,coverage:(rows.length-1-warmup)>0?trades/(rows.length-1-warmup):0,
      records,explanation:'Walk-forward: правила з попередніх завершених свічок, результат лише наступної закритої свічки. Без комісій, затримки чи моделювання OTC.'};
  }
  function backtestMulti(inputM1,inputM5,opts={}){
    const one=normalize(inputM1),five=normalize(inputM5);
    const payout=opts.payout===undefined?.9:Number(opts.payout);
    if(!(payout>0&&payout<=1))throw Error('Виплата повинна бути в межах (0;1].');
    const m1Step=60000,m5Step=300000;
    if(one.some((x,i)=>i>0&&x.start-one[i-1].start!==m1Step)||
       five.some((x,i)=>i>0&&x.start-five[i-1].start!==m5Step))
      throw Error('У M1 або M5 є пропуски; walk-forward неможливий.');
    const warmup=80;
    let wins=0,losses=0,ties=0,wait=0,net=0,streak=0,maxLossStreak=0,index=-1;
    const records=[];
    for(let i=warmup;i<one.length-1;i++){
      const closedAt=one[i].start+m1Step;
      // M5 candles must be fully CLOSED before the M1 decision timestamp.
      while(index+1<five.length&&five[index+1].start+m5Step<=closedAt)index++;
      if(index<54){wait++;continue;}
      const m1=analyze(one.slice(0,i+1));
      const m5=analyze(five.slice(0,index+1));
      if(m1.bias==='wait'||(m5.trend!=='sideways'&&m5.trend!==m1.bias)){
        wait++;continue;
      }
      const entry=one[i].close,exit=one[i+1].close;
      if(exit===entry){ties++;continue;}
      const won=(exit>entry)===(m1.bias==='up');
      if(won){wins++;streak=0;net+=payout;}
      else{losses++;streak++;net-=1;}
      maxLossStreak=Math.max(maxLossStreak,streak);
      records.push({start:one[i].start,bias:m1.bias,entry,exit,won,
        m5LastClosedAt:five[index].start+m5Step});
    }
    const trades=wins+losses,slots=Math.max(0,one.length-1-warmup);
    return {payout,trades,wins,losses,ties,wait,netUnits:net,
      accuracy:trades>=30?100*wins/trades:null,
      rawAccuracy:trades?100*wins/trades:null,maxLossStreak,
      coverage:slots?trades/slots:0,records,
      explanation:'M1 і остання на той момент повністю завершена M5. Обидва таймфрейми без підглядання вперед. Експірація одна M1.'};
  }
  function photoSummary(report){
    if(!report?.reliable||!Array.isArray(report.shapes)||report.shapes.length<16)
      return ['Price Action на фото: контури ненадійні або їх замало; рівні не підтверджені.'];
    const last=report.shapes.slice(-24).sort((a,b)=>a.x-b.x);
    const level=report.structure||{};
    const structure=level.highShape==='higher'&&level.lowShape==='higher'?
      'Вищі контури зверху і знизу (можливе підвищення структури).':
      level.highShape==='lower'&&level.lowShape==='lower'?
      'Нижчі контури зверху і знизу (можливе зниження структури).':
      'Верхні й нижні контури не підтверджують єдиного тренду.';
    const minY=Math.min(...last.map(c=>c.y));
    const maxY=Math.max(...last.map(c=>c.y+c.h));
    const tol=Math.max(4,(maxY-minY)*.09);
    const tops=last.filter(c=>c.y<=minY+tol).length;
    const bottoms=last.filter(c=>c.y+c.h>=maxY-tol).length;
    return ['Price Action · структура: '+structure,
      'Верхня/нижня видимі зони: '+tops+'/'+bottoms+
      ' дотиків контурів (пікселі фото, не біржові котирування).',
      'Трикутники та пробої за фото без повних OHLC не підтверджуються. Для перевірки відкрий ринковий модуль нижче.'];
  }
  return Object.freeze({analyze,backtest,backtestMulti,photoSummary,normalize});
});
