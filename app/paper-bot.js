(()=>{'use strict';
const $=id=>document.getElementById(id),KEY='myshka-auto-paper-v1';
let running=false,busy=false,timer=null,history=[],pending=null,lastCandle='',lastPair='',lastPrice=NaN;
try{const saved=JSON.parse(localStorage.getItem(KEY)||'{}');history=Array.isArray(saved.history)?saved.history.slice(0,250):[];pending=saved.pending||null;}catch{}
function save(){try{localStorage.setItem(KEY,JSON.stringify({history:history.slice(0,250),pending}));}catch{}}
function money(n){return Number(n).toLocaleString('uk-UA',{maximumFractionDigits:2,minimumFractionDigits:2});}
function status(s){$('status').textContent=s}
function ema(a,n){let e=a[0],k=2/(n+1);for(const v of a.slice(1))e=v*k+e*(1-k);return e}
function rsi(a){const diff=a.slice(1).map((v,i)=>v-a[i]);const d=diff.slice(-14),g=d.reduce((s,x)=>s+Math.max(0,x),0)/14,l=d.reduce((s,x)=>s+Math.max(0,-x),0)/14;return l===0?(g===0?50:100):100-100/(1+g/l)}
async function fetchMarket(pair){
 const base='https://api.binance.com/api/v3';
 const ctrl=new AbortController(),timeout=setTimeout(()=>ctrl.abort(),10000);
 try{const [candles,ticker]=await Promise.all([
 fetch(base+'/klines?symbol='+pair+'&interval=1m&limit=80',{signal:ctrl.signal,cache:'no-store'}),
 fetch(base+'/ticker/price?symbol='+pair,{signal:ctrl.signal,cache:'no-store'})]);
 if(!candles.ok||!ticker.ok)throw Error('Binance HTTP '+candles.status+'/'+ticker.status);
 const [ks,pr]=await Promise.all([candles.json(),ticker.json()]);
 const now=Date.now(),closed=ks.filter(c=>Number(c[6])<now-1000);
 const price=Number(pr.price);
 if(closed.length<35||!Number.isFinite(price)||price<=0)throw Error('Недостатньо свічок або немає ціни');
 return {closed,price};
 }finally{clearTimeout(timeout)}
}
function render(){
 const wins=history.filter(x=>x.outcome==='WIN').length,losses=history.filter(x=>x.outcome==='LOSS').length;
 $('pnl').textContent=money(history.reduce((s,x)=>s+(Number(x.pnl)||0),0));
 $('score').textContent=(wins+losses)+' / '+wins;
 $('pending').textContent=pending?pending.pair+' · '+pending.direction+' · вхід '+pending.entry+' · до '+new Date(pending.due).toLocaleTimeString('uk-UA'):'Немає відкритої демоугоди.';
 $('rows').replaceChildren();
 if(!history.length){const tr=document.createElement('tr'),td=document.createElement('td');td.colSpan=5;td.textContent='Поки порожньо';tr.append(td);$('rows').append(tr)}
 for(const item of history.slice(0,40)){const tr=document.createElement('tr');for(const value of [new Date(item.at).toLocaleString('uk-UA'),item.pair,item.direction,item.entry+' → '+item.exit,item.outcome+' ('+(item.pnl>=0?'+':'')+money(item.pnl)+')']){const td=document.createElement('td');td.textContent=value;tr.append(td)}$('rows').append(tr)}
}
async function tick(){
 if(!running||busy)return;busy=true;
 try{
 const pair=pending?.pair||$('pair').value;
 const {closed,price}=await fetchMarket(pair);lastPrice=price;$('price').textContent=money(price);
 if(pending){
 if(Date.now()>=pending.due){
 const win=pending.direction==='UP'?price>pending.entry:price<pending.entry;
 const tie=price===pending.entry;
 history.unshift({...pending,exit:price,outcome:tie?'TIE':win?'WIN':'LOSS',pnl:tie?0:win?9.2:-10,settledAt:Date.now()});
 status('Демоугода завершена за отриманою публічною ціною. '+(tie?'Нічия':win?'Влучив':'Помилився'));
 pending=null;save();
 }else status('Демоугода відкрита. Очікуємо завершення 60 с.');
 }else{
 const closes=closed.map(c=>Number(c[4])),fast=ema(closes.slice(-40),9),slow=ema(closes.slice(-60),21),momentum=rsi(closes);
 const last=closed[closed.length-1],id=pair+':'+last[0],up=fast>slow&&momentum>=55&&momentum<=70,down=fast<slow&&momentum<=45&&momentum>=30;
 const direction=up?'UP':down?'DOWN':'STOP';
 $('signal').textContent=direction;
 if(direction!=='STOP'&&id!==lastCandle){
 pending={pair,direction,entry:price,at:Date.now(),due:Date.now()+60000,candle:id};
 lastCandle=id;save();
 status('Відкрито ВІРТУАЛЬНУ угоду '+direction+'. EMA9='+money(fast)+', EMA21='+money(slow)+', RSI='+money(momentum));
 }else status('JEV аналізує. EMA9='+money(fast)+', EMA21='+money(slow)+', RSI='+money(momentum)+'. '+(direction==='STOP'?'Умов для входу немає.':'На цій свічці повторного входу немає.'));
 }
 render();
 }catch(e){status('⚠️ Немає доступу до публічних цін: '+String(e.message||e)+'. Угоди не створюються, доки немає даних.');$('signal').textContent='СТОП';}
 finally{busy=false}
}
$('start').onclick=()=>{running=true;$('start').disabled=true;$('stop').disabled=false;$('pair').disabled=true;tick();timer=setInterval(tick,15000)};
$('stop').onclick=()=>{running=false;clearInterval(timer);$('start').disabled=false;$('stop').disabled=true;$('pair').disabled=false;status('Зупинено. Якщо угода залишилася відкритою, вона перевіриться після наступного запуску.')};
$('reset').onclick=()=>{if(!confirm('Видалити всі локальні деморезультати?'))return;history=[];pending=null;lastCandle='';save();render();status('Деможурнал очищено.')};
if(pending)status('Є незавершена угода з попереднього сеансу. Натисни запуск, щоб перевірити її за новою ціною (не точною ціною експірації).');
render();
})();