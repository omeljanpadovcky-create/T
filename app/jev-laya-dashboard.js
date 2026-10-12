/* Passive public market research dashboard. Does not place/copy trades. */
(() => {
  const $=id=>document.getElementById(id);
  const URL='./data/jev-laya-research.json';
  const percent=value=>value!==null&&value!==undefined&&Number.isFinite(Number(value))?
    (100*Number(value)).toLocaleString('uk-UA',{maximumFractionDigits:1})+' %':'—';
  const dateTime=value=>value?
    new Date(value).toLocaleString('uk-UA',{dateStyle:'short',timeStyle:'short'}):'невідомо';
  async function refresh(){
    const badge=$('laya-status');
    if(!badge)return;
    badge.textContent='Читаємо збережений звіт GitHub…';
    try{
      const response=await fetch(URL+'?ts='+Date.now(),{cache:'no-store'});
      if(!response.ok)throw Error('Звіт ще не опубліковано (HTTP '+response.status+')');
      const data=await response.json();
      if(data.version!==1||data.real_orders!==false||data.not_pocket_option!==true||
        data.model!=='multinomial_logistic_baseline_not_laya')
        throw Error('Непідтверджений формат звіту.');
      const holdout=data.chronological_purged_holdout||{};
      const samples=data.pair_samples||{};
      const train=Object.values(samples).reduce((s,x)=>s+Number(x.train||0),0);
      const age=Date.now()-Date.parse(data.trained_at||'');
      const stale=!Number.isFinite(age)||age>36*3600*1000||age< -1800000;
      $('laya-trained-count').textContent=String(train);
      $('laya-test-count').textContent=String(Number(holdout.examples||0));
      $('laya-winrate').textContent=percent(holdout.win_rate_excluding_ties);
      const trades=Number(holdout.predicted_trades||0);
      badge.textContent=(stale?'🟠 Звіт застарів · ':'🟢 Звіт оновлено · ')+
        dateTime(data.trained_at)+' · Laya в активному JEV: НЕ ПІДКЛЮЧЕНО';
      $('laya-compare').textContent='Лише логістичний baseline, не Laya: '+
        'паперових рішень '+trades+', WIN '+Number(holdout.wins||0)+
        ' / LOSS '+Number(holdout.losses||0)+' / TIE '+Number(holdout.ties||0)+
        ', STOP '+Number(holdout.stops||0)+
        '; умовний P&L '+Number(holdout.hypothetical_pnl_usdt||0).toLocaleString('uk-UA')+
        ' USDT. Достатній доказ переваги: '+(data.research_quality_gate_passed===true?'так (лише дослідження)':'ні')+
        '. Жодних реальних угод, а дані Pocket Option OTC недоступні.';
    }catch(error){
      badge.textContent='⚠️ '+String(error.message||error);
      $('laya-compare').textContent='Коли фоновий запуск створить файл, тут буде хронологічна перевірка без вигаданої точності.';
    }
  }
  function init(){
    if(!$('laya-refresh'))return;
    $('laya-refresh').addEventListener('click',refresh);
    refresh();
    setInterval(()=>{if(!$('screen-autodemo')?.hidden)refresh();},120000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});
  else init();
})();