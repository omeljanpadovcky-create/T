(()=>{'use strict';
const $=id=>document.getElementById(id);
const fmt=n=>Number(n).toLocaleString('uk-UA',{minimumFractionDigits:2,maximumFractionDigits:2});
const stamp=x=>{if(!x)return '—';const d=new Date(x);return Number.isNaN(d.getTime())?'—':d.toLocaleString('uk-UA')};
let busy=false;
async function refresh(){
 if(busy)return;busy=true;$('auto-status').textContent='Перевіряємо журнал…';
 try{
 const res=await fetch('./data/btc-paper.json?nocache='+Date.now(),{cache:'no-store'});
 if(!res.ok)throw Error('HTTP '+res.status+' — журнал поки не опублікований');
 const data=await res.json(),trades=Array.isArray(data.trades)?data.trades:[];
 const wins=trades.filter(t=>t.outcome==='WIN').length,losses=trades.filter(t=>t.outcome==='LOSS').length;
 const pnl=trades.reduce((sum,t)=>sum+(Number(t.pnl)||0),0);
 $('auto-total').textContent=String(trades.length);
 $('auto-winloss').textContent=wins+' / '+losses;
 $('auto-pnl').textContent=fmt(pnl)+' USDT';
 $('auto-signal').textContent=data.insights?.direction||'—';
 const checked=new Date(data.checked_at||0).getTime(),age=Date.now()-checked;
 const stale=!Number.isFinite(age)||age>20*60*1000||age< -60000;
 $('auto-badge').textContent=data.status!=='ok'?'🔴 ПОМИЛКА':stale?'🟠 ДАНІ ЗАСТАРІЛИ':'🟢 ДАНІ ОНОВЛЕНО';
 $('auto-status').textContent='Останній запуск: '+stamp(data.checked_at)+' · Джерело: '+(data.source||'невідоме')+(data.error?' · Помилка: '+data.error:'')+(stale?' · Оновлення запізнюється.':'');
 $('auto-pending').textContent=data.pending?'Напрям '+data.pending.direction+' · BTC/USDT · умовний вхід '+fmt(data.pending.entry)+' USDT · термін '+stamp(data.pending.due_ms):'Немає активної віртуальної угоди.';
 const list=$('auto-trades');list.replaceChildren();
 if(!trades.length){const p=document.createElement('p');p.className='hint';p.textContent='Угод ще немає. Це нормально, якщо стратегія показує СТОП або ринкові дані недоступні.';list.append(p);}
 for(const t of trades.slice(0,20)){
 const card=document.createElement('div');card.className='journal-card';
 const title=document.createElement('strong');title.textContent=(t.direction||'?')+' · '+(t.outcome||'?')+' · '+(Number(t.pnl)>=0?'+':'')+fmt(t.pnl||0)+' USDT';
 const info=document.createElement('p');info.className='hint';info.textContent=stamp(t.settled_at||t.recorded_at)+' · '+fmt(t.entry)+' → '+fmt(t.exit);
 card.append(title,info);list.append(card);
 }
 }catch(e){$('auto-badge').textContent='🔴 НЕМАЄ ДАНИХ';$('auto-status').textContent='Не вдалося завантажити журнал: '+String(e.message||e);}
 finally{busy=false}
}
$('auto-refresh')?.addEventListener('click',refresh);
document.querySelectorAll('[data-go="autodemo"]').forEach(el=>el.addEventListener('click',refresh));
window.addEventListener('hashchange',()=>{if(location.hash==='#autodemo')refresh()});
if(location.hash==='#autodemo')refresh();
setInterval(()=>{if(location.hash==='#autodemo'&&!document.hidden)refresh()},60000);
})();