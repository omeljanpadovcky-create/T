/* JEV: transparent paper results for two video-inspired hypotheses (NO broker connection). */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const SOURCE='./data/trader-video-study.json';
  const formatPct=value=>value===null||value===undefined||!Number.isFinite(Number(value))?
    '—':(Number(value)*100).toLocaleString('uk-UA',{maximumFractionDigits:1})+' %';
  const fmt=value=>Number(value).toLocaleString('uk-UA',{maximumFractionDigits:2})+' $';
  const names={pullback_follow:'Відкат + підтвердження свічки',
               breakout_follow:'Пробій попереднього діапазону'};
  function card(title,detail,stats,last){
    const el=document.createElement('article');el.className='journal-card';
    const wrap=document.createElement('div');
    const heading=document.createElement('strong');heading.textContent=title;
    const description=document.createElement('small');description.textContent=detail;
    const scored=document.createElement('small');scored.textContent=stats;
    wrap.append(heading,description,scored);
    if(last){const note=document.createElement('small');note.textContent=last;wrap.append(note);}
    el.append(wrap);return el;
  }
  async function refresh(){
    const status=$('video-study-status'),container=$('video-study-strategies');
    if(!status||!container)return;
    status.textContent='Читаємо звіт із GitHub…';
    try {
      const response=await fetch(SOURCE+'?t='+Date.now(),{cache:'no-store'});
      if(!response.ok)throw Error('Звіт поки відсутній (HTTP '+response.status+')');
      const data=await response.json();
      if(data.version!==1||data.real_orders!==false||data.not_pocket_option!==true||
        data.copied_trader_trades!==0||data.video_labels_verified!==false)
        throw Error('Невірні або непідтверджені дані дослідження.');
      const elapsed=Date.now()-Date.parse(data.updated_at||'');
      const stale=!Number.isFinite(elapsed)||elapsed>90*60*1000||elapsed< -30*60*1000;
      const published=Number.isFinite(elapsed)?new Date(data.updated_at).toLocaleString('uk-UA'):'—';
      status.textContent=(stale?'🟠 Застарілі дані':'🟢 Звіт оновлено')+
        ' · '+published+' · '+data.price_source;
      $('video-study-market').textContent='Kraken 5m';
      const results=Object.values(data.forward_results||{});
      const wins=results.reduce((s,r)=>s+(Number(r.wins)||0),0);
      const losses=results.reduce((s,r)=>s+(Number(r.losses)||0),0);
      $('video-study-forward').textContent=wins+' / '+losses;
      const pass=results.some(r=>r.passes_research_gate===true);
      $('video-study-edge').textContent=pass?'Є дослідницький сигнал (не торгувати)':'Не підтверджено';
      container.replaceChildren();
      const errors=Object.entries(data.source_errors||{});
      if(errors.length){
        const notice=document.createElement('p');
        notice.className='notice';
        notice.textContent='Проблеми з ринковими даними: '+errors.map(([pair,message])=>pair+' — '+message).join('; ');
        container.append(notice);
      }
      for(const [key,title] of Object.entries(names)){
        const historic=data.retrospective_final_20pct?.[key];
        const forward=data.forward_results?.[key];
        const desc=data.strategies?.[key]||'Фіксоване правило';
        if(!historic||!forward)continue;
        const statline='Історична контрольна ділянка: '+historic.wins+' WIN / '+
          historic.losses+' LOSS / '+historic.ties+' TIE · точність '+formatPct(historic.win_rate)+
          '. Перспективний журнал: '+forward.wins+' WIN / '+
          forward.losses+' LOSS / '+forward.ties+' TIE · точність '+formatPct(forward.win_rate)+
          '. Умовний P&L '+fmt(forward.illustrative_usd)+' (не прибуток брокера).';
        const last=(data.events||[]).find(x=>x.strategy===key);
        let lastInfo='Нових зареєстрованих BUY/SELL ще немає; STOP не є помилкою.';
        if(last){
          lastInfo='Останній запис: '+last.pair+' · '+last.direction+' · '+
            ({OPEN:'очікуємо завершеної свічки',WIN:'WIN',LOSS:'LOSS',TIE:'TIE'}[last.status]||'невідомо')+
            ' · '+new Date(last.created_at).toLocaleString('uk-UA');
        }
        container.append(card(title,desc,statline,lastInfo));
      }
    }catch(error){
      $('video-study-market').textContent='—';
      $('video-study-forward').textContent='—';
      $('video-study-edge').textContent='Невідомо';
      status.textContent='⚠️ '+String(error.message||error);
      container.replaceChildren();
      const message=document.createElement('p');message.className='hint';
      message.textContent='Поки немає підтвердженого звіту. Ніякі WIN/LOSS не вигадуємо.';
      container.append(message);
    }
  }
  function init(){
    const button=$('video-study-refresh');if(!button)return;
    button.addEventListener('click',refresh);
    refresh();
    setInterval(()=>{if(!$('screen-autodemo')?.hidden)refresh();},120000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();