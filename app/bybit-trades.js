/* User-supplied Bybit Master Trader history: local-only, no credentials, no execution. */
(() => {
'use strict';
const input=document.getElementById('bybit-trades-file'),status=document.getElementById('bybit-trades-status'),target=document.getElementById('bybit-trades-table'),clear=document.getElementById('bybit-trades-clear');
if(!input||!status||!target)return;
const key='myshka.bybit.verified-trades.v1';
const cleanText=(v,max=100)=>typeof v==='string'?v.trim().slice(0,max):'';
const validDate=v=>typeof v==='string'&&!Number.isNaN(Date.parse(v))?new Date(v).toISOString():'';
let latestWatchlist=[],latestWatchTrades=[],latestWatchOrigin='не завантажено';
const watchStatus=document.getElementById('bybit-watchlist-status'),watchGrid=document.getElementById('bybit-watchlist-grid');
const copyButton=document.getElementById('bybit-watchlist-copy'),copyStatus=document.getElementById('bybit-watchlist-copy-status');
const formatPct=n=>Number.isFinite(n)?n.toFixed(2).replace('.',',')+'%':'—';
function evidenceForTrader(name){
 const subset=latestWatchTrades.filter(t=>t.trader.toLocaleLowerCase()===name.toLocaleLowerCase());
 const closed=subset.filter(t=>t.closed&&t.exit>0);
 const moves=closed.map(t=>(t.exit/t.entry-1)*(t.side==='Buy'||t.side==='Long'?100:-100));
 const wins=moves.filter(x=>x>0).length;
 const mean=moves.length?moves.reduce((a,b)=>a+b,0)/moves.length:null;
 return {subset,closed,wins,mean,winPct:closed.length?100*wins/closed.length:null};
}
function renderWatchlist(){
 if(!watchGrid||!watchStatus)return;
 watchGrid.replaceChildren();
 if(!latestWatchlist.length){watchStatus.textContent='Поки немає доступного списку десяти трейдерів';return;}
 const available=latestWatchlist.filter(t=>evidenceForTrader(t.name).subset.length>0).length;
 watchStatus.textContent=latestWatchlist.length+' учасників архівного рейтингу · '+available+' із наданою історією угод · '+latestWatchOrigin+'. Це не актуальний ТОП-10.';
 for(const t of latestWatchlist){
  const stat=evidenceForTrader(t.name);
  const card=document.createElement('article');
  card.style.cssText='border:1px solid rgba(125,140,165,.35);border-radius:12px;padding:12px;min-width:0;overflow-wrap:anywhere';
  const h=document.createElement('strong');h.textContent='#'+t.event_rank_at_previous_index+' · '+t.name;
  const note=document.createElement('p');note.style.cssText='font-size:12px;margin:7px 0';
  note.textContent='Місце в минулому рейтингу події · не поточне';
  const details=document.createElement('p');details.style.cssText='font-size:12px;margin:5px 0';
  details.textContent=stat.subset.length?
   stat.subset.length+' записів · '+stat.closed.length+' закритих · '+(stat.closed.length?formatPct(stat.winPct)+' напрямків у плюс':'результат невідомий'):
   'Історії угод немає · LIVE невідомий';
  const risk=document.createElement('small');
  risk.textContent=stat.closed.length?'Сер. рух ціни за напрямком: '+formatPct(stat.mean)+' · не ROI/P&L':'Немає даних про просадку, плечі чи прибуток';
  card.append(h,note,details,risk);watchGrid.appendChild(card);
 }
}
async function loadWatchlist(){
 if(!watchStatus)return;
 try{
  const resp=await fetch('./crypto_myshka/data/bybit_master_watchlist.json?ts='+Date.now(),{cache:'no-store'});
  if(!resp.ok)throw Error('HTTP '+resp.status);
  const data=await resp.json();
  if(data.ranking_is_current!==false||data.live_positions_available!==false||!Array.isArray(data.traders)||data.traders.length!==10)throw Error('некоректний список');
  if(data.traders.some(t=>typeof t.name!=='string'||!t.name.trim()))throw Error('немає імен');
  latestWatchlist=data.traders;renderWatchlist();
 }catch(e){watchStatus.textContent='Список поки недоступний ('+e.message+')';}
}
copyButton?.addEventListener('click',async()=>{
 const entries=latestWatchlist.map(t=>{
  const a=evidenceForTrader(t.name);
  return {trader:t.name,past_event_rank:t.event_rank_at_previous_index,imported_records:a.subset.length,closed_records:a.closed.length,
    price_direction_win_pct:a.winPct,mean_directional_price_move_pct:a.mean,
    trades:a.subset.slice(0,15).map(x=>({symbol:x.symbol,side:x.side,opened_at:x.opened,entry_price:x.entry,closed_at:x.closed,exit_price:x.exit,source_url:x.url}))};
 });
 const prompt='JEV, зроби суто дослідницький огляд десяти трейдерів із архівного списку Bybit. ЦЕ НЕ ПОТОЧНИЙ ТОП-10. Дані імпорту неперевірені. Не домислюй угоди, ROI, winrate, кредитне плече чи прибуток. Якщо історії немає — так і напиши. Порівняй тільки ті записи, що надані, їхній розмір вибірки, можливі ризики й відсутні дані. Жодних торгових сигналів.\n'+JSON.stringify({source:'historic_event_names',trade_source:latestWatchOrigin,as_of:new Date().toISOString(),traders:entries});
 try{
  if(!navigator.clipboard?.writeText)throw Error('Clipboard API не підтримується');
  await navigator.clipboard.writeText(prompt);
  if(copyStatus)copyStatus.textContent='Звіт скопійовано. Можеш вставити його в чат JEV або ChatGPT.';
 }catch{if(copyStatus)copyStatus.textContent='Копіювання недоступне в цьому браузері. Використай імпорт JSON або відкрий сторінку через HTTPS.';}
});

function normalize(raw){
 if(!raw||!Array.isArray(raw.trades)||raw.trades.length>3000)throw Error('Очікується масив trades (до 3000 записів)');
 const seen=new Set(),trades=[];
 for(const row of raw.trades){
  if(!row||typeof row!=='object')continue;
  const trader=cleanText(row.trader,80),symbol=cleanText(row.symbol,30).toUpperCase(),side=cleanText(row.side,12),opened=validDate(row.opened_at);
  const entry=Number(row.entry_price),closed=validDate(row.closed_at),exit=Number(row.exit_price);
  const url=cleanText(row.source_url,400);
  if(!trader||!/^([A-Z0-9]{4,20})$/.test(symbol)||!['Buy','Sell','Long','Short'].includes(side)||!opened||!(entry>0))continue;
  if(url&&(!url.startsWith('https://www.bybit.com/')&&!url.startsWith('https://bybit.com/')))continue;
  const fingerprint=[trader,symbol,side,opened,entry].join('|');
  if(seen.has(fingerprint))continue;seen.add(fingerprint);
  trades.push({trader,symbol,side,opened,entry,closed,exit:closed&&exit>0?exit:null,url});
 }
 return trades.slice(0,1000);
}
function render(trades){
 latestWatchTrades=trades;
 renderWatchlist();
 target.replaceChildren();
 if(!trades.length){status.textContent='Немає коректних записів угод';return;}
 const traders=new Set(trades.map(t=>t.trader));
 const closed=trades.filter(t=>t.closed&&t.exit);
 const positive=closed.filter(t=>(t.side==='Buy'||t.side==='Long'?t.exit-t.entry:t.entry-t.exit)>0).length;
 status.textContent=`Імпортовано ${trades.length} унікальних угод · ${traders.size} трейдерів · ${closed.length} закритих · ${closed.length?Math.round(positive/closed.length*100)+'% напрямків у плюс':'результат невідомий'} (без комісій, funding і розміру позицій). Джерело: імпорт користувача, не LIVE.`;
 const table=document.createElement('table');table.style.cssText='width:100%;text-align:left;font-size:12px';
 const header=document.createElement('tr');
 for(const v of ['Трейдер','Пара','Напрям','Відкрито','Вхід','Вихід','Результат']){const th=document.createElement('th');th.textContent=v;header.appendChild(th)}
 table.appendChild(header);
 for(const t of trades.slice(0,100)){
  const tr=document.createElement('tr');
  const direction=t.side==='Buy'||t.side==='Long'?1:-1;
  const result=t.exit?((t.exit/t.entry-1)*direction*100).toFixed(2)+'%*':'відкрита / невідомо';
  for(const v of [t.trader,t.symbol,t.side,t.opened.slice(0,16),String(t.entry),t.exit?String(t.exit):'—',result]){const td=document.createElement('td');td.textContent=v;td.style.padding='6px 9px 6px 0';tr.appendChild(td)}
  table.appendChild(tr);
 }
 target.appendChild(table);
 const note=document.createElement('small');note.textContent='*Зміна ціни за напрямком, не ROI/P&L. Дані не верифіковано незалежно. Показано до 100 рядків.';target.appendChild(note);
}
input.addEventListener('change',async()=>{
 const file=input.files?.[0];if(!file)return;
 if(file.size>1500000){status.textContent='Файл завеликий (макс. 1,5 МБ)';return;}
 try{const trades=normalize(JSON.parse(await file.text()));if(!trades.length)throw Error('Немає коректних угод');localStorage.setItem(key,JSON.stringify(trades));latestWatchOrigin='локальний JSON користувача (не перевірений незалежно)';render(trades)}
 catch(e){status.textContent='Помилка імпорту: '+e.message;}
 input.value='';
});
clear?.addEventListener('click',()=>{localStorage.removeItem(key);render([]);status.textContent='Імпорт очищено';});
try{const saved=JSON.parse(localStorage.getItem(key)||'[]');if(Array.isArray(saved)&&saved.length){latestWatchOrigin='локальний JSON (не перевірений незалежно)';render(saved)}}catch{localStorage.removeItem(key)}
const autoStatus=document.getElementById('bybit-auto-status'),autoRefresh=document.getElementById('bybit-auto-refresh');
async function loadAuto(){
 if(!autoStatus)return;
 autoStatus.textContent='Перевіряємо архів Master Traders…';
 try{
  const res=await fetch('./crypto_myshka/data/bybit_master_research.json?ts='+Date.now(),{cache:'no-store'});
  if(!res.ok)throw Error('архів ще не опубліковано');
  const data=await res.json();
  if(data.status!=='ok'||!Array.isArray(data.trades)||!data.trades.length){
   autoStatus.textContent='Автоматичний архів: '+(data.status==='unconfigured'?'очікує дозволеного джерела угод':'угод немає')+'. LIVE не підключено.';
   return;
  }
  const trades=normalize({trades:data.trades});
  if(!trades.length)throw Error('архів не містить перевірених записів');
  autoStatus.textContent='Автоархів: '+trades.length+' угод, оновлено '+String(data.updated_at||'невідомо')+'. Дані джерела не верифіковані незалежно.';
  if(!localStorage.getItem(key)){latestWatchOrigin='автоархів (джерело не перевірене незалежно)';render(trades);}
 }catch(e){autoStatus.textContent='Автоматичний архів поки недоступний: '+e.message;}
}
autoRefresh?.addEventListener('click',loadAuto);
loadAuto();
loadWatchlist();
})();
