/* Separate TradeMyshka video library — public metadata, no video scraping in browser.
 * Never fabricate video analyses: JEV summaries must carry status=model_summary.
 */
(() => {
  'use strict';
  const SOURCE = './crypto_myshka/data/youtube_archive.json';
  const $ = id => document.getElementById(id);
  const esc = value => String(value == null ? '' : value).replace(/[&<>"']/g,
    k => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[k]));
  const text = (v, max = 500) => String(v == null ? '' : v).slice(0,max);
  const arr = value => Array.isArray(value) ? value : [];
  const validId = value => /^[A-Za-z0-9_-]{11}$/.test(text(value));
  const translate = {
    videos: 'Відео',
    streams: 'Запис ефіру',
    shorts: 'Shorts',
    captions_scanned: 'Субтитри прочитано',
    title_description_only: 'Назва й опис',
    legacy_metadata_only: 'Раніше знайдений',
    metadata_only: 'Метадані',
  };
  const state = {data:null, busy:false, loadedAt:0, failedAt:0,
    limit:12, query:'', channel:'', kind:'', evidence:'', listenersReady:false, channelsReady:false, error:null};
  const niceDate = x => {
    if (!/^\d{8}$/.test(String(x||''))) return 'Дата публікації невідома';
    return x.slice(6,8)+'.'+x.slice(4,6)+'.'+x.slice(0,4);
  };
  const sample = row => {
    const a=row.analysis||{}, j=row.jev||{};
    return [
      row.title, row.channel_name, row.kind,
      ...arr(a.mentioned_instruments), ...arr(a.pairs), ...arr(a.mentioned_indicators),
      ...arr(a.mentioned_timeframes), j.summary, j.strategy,
      ...arr(row.gemini?.pairs), ...arr(row.gemini?.indicators), ...arr(row.gemini?.timeframes),
      row.gemini?.summary, row.gemini?.strategy, row.gemini?.visual_context
    ].join(' ').toLocaleLowerCase('uk-UA');
  };
  function filters(row) {
    if (state.channel && row.channel_id !== state.channel) return false;
    if (state.kind && row.kind !== state.kind) return false;
    if (state.evidence === 'gemini' && row.gemini?.status !== 'gemini_video_summary') return false;
    if (state.evidence === 'subtitles' && row.caption_status !== 'available') return false;
    if (state.evidence === 'jev' && row.jev?.status !== 'model_summary') return false;
    if (state.evidence === 'metadata' && (row.caption_status === 'available' || row.gemini?.status === 'gemini_video_summary' || row.jev?.status === 'model_summary')) return false;
    return !state.query || sample(row).includes(state.query);
  }
  function entry(row) {
    if (!validId(row.id)) return '';
    const a=row.analysis||{}, j=row.jev||{}, g=row.gemini||{};
    const id=row.id;
    const videoUrl='https://www.youtube.com/watch?v='+id;
    const thumb='https://i.ytimg.com/vi/'+id+'/mqdefault.jpg';
    const instruments=[...new Set([...arr(g.pairs),...arr(a.mentioned_instruments),...arr(a.pairs)])].slice(0,8);
    const indicators=[...new Set([...arr(g.indicators),...arr(a.mentioned_indicators)])].slice(0,6);
    const timeframes=[...new Set([...arr(g.timeframes),...arr(a.mentioned_timeframes)])].slice(0,6);
    const badges=[
      ...instruments.map(s=>'<span class="archive-tag">'+esc(text(s,32))+'</span>'),
      ...indicators.map(s=>'<span class="archive-tag soft">'+esc(text(s,32))+'</span>'),
      ...timeframes.map(s=>'<span class="archive-tag faded">'+esc(text(s,20))+'</span>')
    ].join('');
    const hasJeV=j.status==='model_summary';
    const hasGemini=g.status==='gemini_video_summary';
    const hasCaptions=row.caption_status==='available';
    const moments=arr(g.moments).slice(0,6).map(m=>
      '<li><b>'+esc(text(m.timestamp,12))+'</b> — '+esc(text(m.observation,170))+'</li>').join('');
    const audiovisual=hasGemini
      ?'<div class="archive-jev"><b>✦ Gemini · аналіз відео та звуку</b>'+
       '<p>'+esc(text(g.summary,650))+'</p>'+
       '<p><strong>Стратегія:</strong> '+esc(text(g.strategy||'Не визначено',650))+'</p>'+
       (g.visual_context?'<p><strong>Графік у кадрі:</strong> '+esc(text(g.visual_context,650))+'</p>':'')+
       (g.audio_context?'<p><strong>Пояснення голосом:</strong> '+esc(text(g.audio_context,650))+'</p>':'')+
       (moments?'<p><strong>Моменти відео (за AI):</strong></p><ul>'+moments+'</ul>':'')+
       '<p><strong>Ризики й обмеження:</strong> '+esc(text(g.risk||'Дані біржі та результат угод не перевірені',650))+'</p>'+
       '<p class="archive-warning">Gemini аналізує відеокадри й звук, але може пропустити миттєві дії та помилитися.</p></div>'
      :'';
    const subtitleNotes=hasJeV
      ?'<div class="archive-jev"><b>🧠 JEV: конспект субтитрів</b><p>'+esc(text(j.summary))+
        '</p><p><strong>Про що говорять:</strong> '+esc(text(j.strategy||'Не визначено'))+
        '</p><p><strong>Обмеження:</strong> '+esc(text(j.risk||'Твердження автора не підтверджені'))+'</p></div>'
      :'';
    const statement=(audiovisual||subtitleNotes)
      ?(audiovisual+subtitleNotes)
      :'<div class="archive-nodata">'+(hasCaptions
          ?'📋 Згадки витягнуто із субтитрів; Gemini-відеоаналіз ще не отримано.'
          :row.content_status==='metadata_only'||row.content_status==='legacy_metadata_only'
          ?'🕓 Ролик у каталозі. Аналіз відео Gemini ще не отримано.'
          :'ℹ️ Аналіз відео ще не доступний: є лише назва та опис.')+
        '</div>';
    const status=(hasGemini?'✅ Gemini · відео':hasJeV?'✅ JEV · текст':hasCaptions?'🔎 Згадки зі субтитрів':'⚪ Метадані');
    const notes=arr(a.notes).slice(0,2).map(t=>'<li>'+esc(text(t,180))+'</li>').join('');
    return '<article class="archive-card">' +
      '<a class="archive-cover" href="'+videoUrl+'" target="_blank" rel="noopener noreferrer" aria-label="Дивитись на YouTube: '+esc(row.title)+'">' +
        '<img src="'+thumb+'" loading="lazy" width="170" height="96" alt="Обкладинка YouTube-відео" referrerpolicy="no-referrer">' +
        '<span class="archive-kind">'+esc(translate[row.kind]||'Відео')+'</span></a>'+
      '<div class="archive-body">' +
        '<div class="archive-author"><b>'+esc(text(row.channel_name,90))+'</b> · '+esc(niceDate(row.upload_date))+'</div>' +
        '<h3><a href="'+videoUrl+'" target="_blank" rel="noopener noreferrer">'+esc(text(row.title,260))+'</a></h3>' +
        '<div class="archive-badges"><span class="archive-stage">'+status+'</span>'+badges+'</div>' +
        statement +
        '<details class="archive-details"><summary>Джерело й обмеження аналізу</summary>' +
          '<p>'+esc(text(a.source_evidence || a.evidence || 'Опис і назва, без перевірки графіка',220))+'</p>' +
          (notes?'<ul>'+notes+'</ul>':'') +
          '<p>Не підтверджує виконання угод, котирування або заявлену прибутковість. '+(hasGemini?'Gemini працював із відео та звуком (обмежене семплювання кадрів).':hasCaptions?'Є доступні субтитри, але відео Gemini ще не обробляв.':'Зміст відеокадрів не перевірено.')+'</p>' +
        '</details>' +
        '<a class="archive-watch" href="'+videoUrl+'" target="_blank" rel="noopener noreferrer">▶ Відкрити на YouTube ↗</a>' +
      '</div>' +
    '</article>';
  }
  function draw() {
    if (!$('archive-list')) return;
    const d=state.data||{};
    const raw=arr(d.videos).filter(row=>row&&validId(row.id));
    const count=raw.length;
    $('archive-count').textContent=String(count);
    $('archive-gemini-count').textContent=String(raw.filter(x=>x.gemini?.status==='gemini_video_summary').length);
    $('archive-gemini-status').textContent=(d.gemini_configured===true
      ? '🟢 Gemini Video API підключено в останньому зборі. Звіти з’являються поступово з урахуванням квот.'
      : d.gemini_configured===false
      ? '🟠 Gemini Video API ще не підключено. Додай GEMINI_API_KEY у секрети GitHub Actions (інструкція нижче).'
      : 'ℹ️ Очікується підтвердження налаштувань Gemini від наступного запуску архіватора.');
    $('archive-caption-count').textContent=String(raw.filter(x=>x.caption_status==='available').length);
    $('archive-jev-count').textContent=String(raw.filter(x=>x.jev&&x.jev.status==='model_summary').length);
    $('archive-index-status').textContent=d.updated_at
      ? 'Оновлено '+new Date(d.updated_at).toLocaleDateString('uk-UA')
      : 'Очікуємо оновлення';
    const completed=Object.values(d.progress||{}).filter(row=>row&&row.backfill_complete).length;
    const sources=Object.keys(d.progress||{}).length;
    $('archive-coverage').textContent='Архів поповнюється: '+count+' доступних роликів. '+
      (sources?('Переглянуто до кінця каталогів: '+completed+'/'+sources+'. '):'Обхід старих відео ще не починався. ')+
      'Повноту YouTube не гарантовано.';
    if (!state.channelsReady) {
      const select=$('archive-channel');
      for(const ch of arr(d.channels)){
        if(!ch||!ch.id)continue;
        const option=document.createElement('option');
        option.value=String(ch.id);
        option.textContent=String(ch.name||ch.handle||ch.id);
        select.append(option);
      }
      state.channelsReady=true;
    }
    const found=raw.filter(filters);
    $('archive-matches').textContent='Знайдено: '+found.length;
    $('archive-more').hidden=state.limit>=found.length;
    if (state.error && !count) {
      $('archive-list').innerHTML='<div class="empty-state"><strong>Архів тимчасово недоступний</strong>'+
        'Перевір з’єднання і спробуй оновити пізніше.</div>';
      return;
    }
    if(!count){
      $('archive-list').innerHTML='<div class="empty-state"><strong>Архів поки порожній</strong>'+
        'Джерела ще збираються або YouTube обмежив доступ. Жодних вигаданих записів.</div>';
      return;
    }
    if(!found.length){
      $('archive-list').innerHTML='<div class="empty-state"><strong>За фільтром роликів немає</strong>'+
        'Спробуй інший канал або індикатор.</div>';
      return;
    }
    $('archive-list').innerHTML=found.slice(0,state.limit).map(entry).join('');
  }
  async function update() {
    if(state.busy) return;
    state.busy=true;
    try{
      const controller=new AbortController();
      const timeout=setTimeout(()=>controller.abort(),16000);
      let response;
      try { response=await fetch(SOURCE+'?v='+Date.now(),{cache:'no-store',signal:controller.signal}); }
      finally {clearTimeout(timeout);}
      if(!response.ok)throw new Error('HTTP '+response.status);
      const parsed=await response.json();
      if(!parsed||!Array.isArray(parsed.videos))throw new Error('Invalid archive feed');
      state.data=parsed;state.error=null;state.loadedAt=Date.now();
    }catch(err){state.error=err;state.failedAt=Date.now();}
    finally {state.busy=false;draw();}
  }
  function render() {
    if(!$('archive-list'))return;
    if(!state.listenersReady){
      $('archive-query').addEventListener('input', e=>{
        state.query=e.target.value.trim().toLocaleLowerCase('uk-UA');state.limit=12;draw();
      });
      $('archive-channel').addEventListener('change',e=>{state.channel=e.target.value;state.limit=12;draw();});
      $('archive-kind').addEventListener('change',e=>{state.kind=e.target.value;state.limit=12;draw();});
      $('archive-evidence').addEventListener('change',e=>{state.evidence=e.target.value;state.limit=12;draw();});
      $('archive-more').addEventListener('click',()=>{state.limit+=12;draw();});
      // Mark listeners as ready; channel <option> population may wait for data.
      state.listenersReady=true;
    }
    if(!state.busy && Date.now()-(state.loadedAt||state.failedAt)>180000)update();
    else if(state.data)draw();
  }
  // Tested via the five-screen DOM smoke suite; no private tokens on page.
  window.MyshkaVideoArchive={render, update, _filters:filters, _state:state};
})();
