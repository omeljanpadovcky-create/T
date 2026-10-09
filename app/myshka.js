/* Crypto Myshka mobile application — no API keys, order execution or fictitious data.
 * All trading context comes from published, timestamped LIVE snapshot JSON.
 * User ratings and saved snapshots remain in this browser's local storage.
 */
(() => {
  'use strict';
  const ENDPOINTS = {
    live: './crypto_myshka/data/youtube_live.json',
    pairs: './crypto_myshka/data/pair_reports.json',
    analysts: './crypto_myshka/data/youtube_analysts.json'
  };
  const STORE = 'crypto-myshka-app-v1';
  const VIEWS = new Set(['home', 'analysis', 'history', 'settings']);
  const allowedTheme = new Set(['light', 'dark']);
  const allowedRefresh = new Set([15, 30, 60, 120]);
  const I18N = {
    trend: { uptrend: 'Висхідний', downtrend: 'Спадний', sideways: 'Боковий', unknown: 'Невідомо' },
    volume: { high: 'Високий', normal: 'Нормальний', low: 'Низький', unknown: 'Невідомо' },
    sentiment: { bullish: 'Бичачий', bearish: 'Ведмежий', neutral: 'Нейтральний', unknown: 'Невідомо' },
    confidence: { medium: 'Середня', low: 'Низька', high: 'Висока', unknown: 'Не визначено' }
  };
  const state = {
    view: 'home', live: null, pairs: null, analysts: null,
    statuses: { live: 'loading', pairs: 'loading', analysts: 'loading' },
    lastSuccessfulFetch: {}, filter: 'all', query: '',
    selectedPair: null, demo: false, refreshing: false, sequence: 0,
    visionStatus: 'checking', visionSource: null, cloudEndpoint: '', cloudAccess: '',
    prefs: { theme: 'light', refresh: 15, saved: {}, votes: {} },
    pollTimer: null
  };
  const $ = id => document.getElementById(id);
  const safe = value => String(value == null ? '' : value).replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const key = report => [report.pair || '', report.observed_at || '', report.channel || ''].join('|');
  const str = value => String(value == null ? '' : value);
  const short = (value, n = 100) => str(value).slice(0, n);
  const arr = value => Array.isArray(value) ? value : [];
  const own = (obj, k) => Object.prototype.hasOwnProperty.call(obj || {}, k);
  const findReports = () => arr(state.pairs && state.pairs.reports);
  const timeMs = x => { const v = Date.parse(x || ''); return Number.isFinite(v) ? v : null; };
  const formatted = x => {
    const t = timeMs(x);
    return t == null ? 'Не визначено' : new Date(t).toLocaleString('uk-UA', { dateStyle: 'short', timeStyle: 'short' });
  };
  const fresh = (date, minutes = 20) => {
    const ms = timeMs(date);
    return ms != null && ms <= Date.now() + 120000 && Date.now() - ms < minutes * 60000;
  };
  const validYoutube = url => {
    try {
      const u = new URL(str(url));
      return u.protocol === 'https:' && (u.hostname === 'www.youtube.com' || u.hostname === 'youtube.com') &&
        /^\/(?:@[\w.-]+(?:\/(?:live|videos|streams))?|watch|live)/.test(u.pathname) ? u.href : null;
    } catch { return null; }
  };
  function toast(msg) {
    const el = $('toast');
    el.textContent = str(msg);
    el.classList.add('show');
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => el.classList.remove('show'), 2800);
  }
  function loadPrefs() {
    try {
      const raw = JSON.parse(localStorage.getItem(STORE) || '{}');
      if (raw && typeof raw === 'object') {
        if (allowedTheme.has(raw.theme)) state.prefs.theme = raw.theme;
        if (allowedRefresh.has(Number(raw.refresh))) state.prefs.refresh = Number(raw.refresh);
        if (raw.saved && typeof raw.saved === 'object' && !Array.isArray(raw.saved)) state.prefs.saved = raw.saved;
        if (raw.votes && typeof raw.votes === 'object' && !Array.isArray(raw.votes)) state.prefs.votes = raw.votes;
      }
    } catch { /* Private storage disabled, app remains functional. */ }
  }
  function persist() {
    try {
      localStorage.setItem(STORE, JSON.stringify(state.prefs));
      return true;
    } catch {
      toast('Браузер не дозволив збереження на пристрої');
      return false;
    }
  }
  const CLOUD_URL_KEY = 'crypto-myshka-cloud-endpoint-v1';
  const CLOUD_ACCESS_KEY = 'crypto-myshka-cloud-access-session-v1';
  function validCloudEndpoint(value) {
    try {
      const url = new URL(String(value).trim());
      if (url.protocol !== 'https:' || !url.hostname || url.username || url.password ||
          url.pathname !== '/' || url.search || url.hash) return null;
      return url.origin;
    } catch { return null; }
  }
  function loadCloudSettings() {
    try { state.cloudEndpoint = validCloudEndpoint(localStorage.getItem(CLOUD_URL_KEY)) || ''; } catch {}
    try { state.cloudAccess = sessionStorage.getItem(CLOUD_ACCESS_KEY) || ''; } catch {}
    $('cloud-endpoint').value = state.cloudEndpoint;
    $('cloud-access').value = state.cloudAccess;
  }
  function updateCloudSettings() {
    const label = $('cloud-connection-status');
    if (!label) return;
    if (!state.cloudEndpoint) label.textContent = 'Хмарний сервер ще не підключено.';
    else if (!state.cloudAccess) label.textContent = 'Введи окремий код доступу JEV.';
    else if (state.visionSource === 'cloud' && state.visionStatus === 'ready')
      label.textContent = '🟢 Хмарний JEV підключено. Фото надсилатиметься на твій сервер і до Gemini.';
    else label.textContent = 'Адресу збережено. Перевірка хмарного JEV: ' +
      (state.visionStatus === 'checking' ? 'очікування…' : 'не готовий або працює локальний JEV.');
  }
  function applyTheme() {
    document.documentElement.dataset.theme = state.prefs.theme;
    document.querySelector('meta[name="theme-color"]').content =
      state.prefs.theme === 'dark' ? '#0b111d' : '#f6f8fc';
    $('theme-select').value = state.prefs.theme;
    $('refresh-select').value = String(state.prefs.refresh);
  }
  function routeView() {
    const hash = location.hash.replace(/^#/, '').toLowerCase();
    return hash === 'live' ? 'analysis' : VIEWS.has(hash) ? hash : 'home';
  }
  function navigate(to, options = {}) {
    if (!VIEWS.has(to)) return;
    state.view = to;
    document.querySelectorAll('[data-screen]').forEach(el => {
      const active = el.dataset.screen === to;
      el.hidden = !active;
      el.classList.toggle('active', active);
    });
    document.querySelectorAll('[data-go]').forEach(el => {
      const active = el.dataset.go === to;
      el.classList.toggle('active', active);
      if (el.matches('.nav-link,.bottom-nav button')) {
        if (active) el.setAttribute('aria-current', 'page');
        else el.removeAttribute('aria-current');
      }
    });
    const names = { home: 'AI Chart Observer', analysis: 'Fast Analysis', history: 'Збережене', settings: 'Налаштування' };
    $('top-context').textContent = names[to];
    document.title = names[to] + ' · Crypto Myshka';
    if (!options.fromHash) history.replaceState(null, '', location.pathname + location.search + '#' + to);
    renderView();
    if (to === 'analysis') checkVisionHealth();
    if (!options.noScroll) window.scrollTo({ top: 0, behavior: 'instant' });
  }
  function link(url, label, additional = '') {
    const good = validYoutube(url);
    return good ? '<a class="small-link ' + additional + '" href="' + safe(good) +
      '" target="_blank" rel="noopener noreferrer">' + safe(label) + ' ↗</a>' : '';
  }
  function empty(icon, title, explanation, goto) {
    return '<div class="empty-state"><span class="empty-icon" aria-hidden="true">' + safe(icon) +
      '</span><strong>' + safe(title) + '</strong><span>' + safe(explanation) + '</span>' +
      (goto ? '<div><button type="button" data-go="' + goto + '" class="small-button">Перейти →</button></div>' : '') + '</div>';
  }
  async function requestJson(url, timeoutMs = 14000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(url + '?t=' + Date.now(), { cache: 'no-store', signal: controller.signal });
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  async function refreshAll(announce = false) {
    if (state.refreshing) return;
    const serial = ++state.sequence;
    state.refreshing = true;
    $('refresh-button').disabled = true;
    const results = await Promise.allSettled(Object.entries(ENDPOINTS).map(async ([name, url]) => {
      const data = await requestJson(url);
      return { name, data };
    }));
    if (serial === state.sequence) {
      results.forEach((result, idx) => {
        const field = Object.keys(ENDPOINTS)[idx];
        if (result.status === 'fulfilled') {
          state[field] = result.value.data;
          state.statuses[field] = 'ok';
          state.lastSuccessfulFetch[field] = new Date().toISOString();
        } else {
          state.statuses[field] = 'error';
        }
      });
      renderAll();
      if (announce) toast('Перевірку джерел завершено');
    }
    state.refreshing = false;
    $('refresh-button').disabled = false;
  }
  function statusPill() {
    const node = $('connection-pill');
    const local = ['localhost', '127.0.0.1'].includes(location.hostname);
    const ready = state.visionStatus === 'ready';
    const label = ready ? (state.visionSource === 'cloud' ? 'JEV хмарний готовий' : 'JEV готовий · локально') :
      state.visionStatus === 'checking' ? 'Перевіряємо JEV' :
      state.visionStatus === 'missing_model' ? 'Потрібна модель Ollama' :
      state.cloudEndpoint ? 'Хмарний JEV не відповідає' :
      local ? 'JEV не відповідає' : 'Підключи хмарний JEV';
    node.className = 'connection-pill ' + (ready ? 'good' : 'warn');
    node.innerHTML = '<span class="dot"></span> ' + label;
    node.title = ready ? 'AI-сервер відповідає. Це не гарантує правильності прогнозу.' :
      'Перевір налаштування JEV і статус сервера.';
  }
  function renderHome() {
    const reports = findReports();
    $('stat-pairs').textContent = String(reports.length);
    const engines = reports.filter(r => r.jev && r.jev.engine === 'separate_ai_explainer' && r.jev.status === 'model');
    $('stat-jev').textContent = state.visionStatus === 'ready' ? 'AI ✓' : engines.length ? 'Звіти AI' : 'Очікує';
    const notice = $('home-notice').querySelector('p');
    const errors = Object.values(state.statuses).filter(x => x === 'error').length;
    if (errors) {
      notice.textContent = 'Архівні звіти можуть бути недоступні. Це не впливає на локальний аналіз скріншотів через JEV.';
    } else if (!reports.length) {
      notice.textContent = 'Поки немає опублікованих звітів за парами. Для власного графіка відкрий Fast Analysis та встав скріншот.';
    } else {
      notice.textContent = 'Дані графіків — спостереження, а не перевірені угоди. Для OTC потрібна особлива обережність із котируваннями.';
    }
  }
  function sourceType(r) {
    if (str(r.pair).toUpperCase().endsWith(' OTC')) return 'OTC';
    const name = str(r.instrument_type).toLowerCase();
    return name.includes('криптовал') ? 'CRYPTO' : 'FOREX / OTHER';
  }
  function reportMarkup(r, savedMode = false) {
    const rid = key(r), save = own(state.prefs.saved, rid), vote = state.prefs.votes[rid] || '';
    const jev = r.jev || {};
    const source = jev.engine === 'separate_ai_explainer' && jev.status === 'model';
    const su = arr(r.support_levels), re = arr(r.resistance_levels);
    const insight = (label, value, cls = '') => '<div class="insight"><span>' + safe(label) + '</span><b class="' + cls + '">' +
      safe(value || 'Не визначено') + '</b></div>';
    const level = (label, list) => list.length ? list.map(x => '<span class="level-tag">' + safe(label) + ': ' + safe(x) + '</span>').join('') : '';
    const levelHtml = level('Підтримка', su) + level('Опір', re) ||
      '<span class="level-tag">Рівні не підтверджено</span>';
    const limit = arr(r.limitations);
    const video = link(r.video_url, 'Джерело на YouTube');
    const type = sourceType(r);
    const sentiment = str(r.sentiment) === 'bearish' ? 'bear' : str(r.sentiment) === 'bullish' ? 'bull' : '';
    const trend = str(r.trend) === 'downtrend' ? 'bear' : str(r.trend) === 'uptrend' ? 'bull' : '';
    return '<article class="report-card" data-report-id="' + safe(rid) + '">' +
      '<div class="report-head"><div><h3>' + safe(r.pair) + '</h3><small>' +
      safe(formatted(r.observed_at)) + ' · ' + safe(r.channel || 'Джерело невідоме') +
      '</small></div><span class="origin-pill ' + (type === 'OTC' ? 'otc' : '') + '">' + safe(type) + '</span></div>' +
      '<div class="report-label">Key insights · Ключові показники</div><div class="insights">' +
      insight('Confidence', I18N.confidence[r.confidence] || 'Не визначено') +
      insight('Trend', I18N.trend[r.trend] || 'Не визначено', trend) +
      insight('Volatility', I18N.volume[r.volatility] || 'Не визначено') +
      insight('Volume', I18N.volume[r.volume] || 'Не визначено') +
      insight('Market sentiment', I18N.sentiment[r.sentiment] || 'Не визначено', sentiment) +
      insight('Спостережень', String(r.observations_count || 1)) +
      '</div><div class="report-label">Підтримка / опір</div><div class="level-row">' + levelHtml + '</div>' +
      '<div class="explanation"><h4>✦ JEV Explanation</h4>' +
      '<p><strong>Чому такий висновок:</strong> ' + safe(jev.why || r.trend_reason || 'Недостатньо даних із кадру.') + '</p>' +
      '<p><strong>Ключові рівні:</strong> ' + safe(jev.key_levels || 'Рівні не перевірено.') + '</p>' +
      '<p><strong>Що перевірити:</strong> ' + safe(jev.watch_next || 'Додаткові свічки, часовий масштаб і незалежні ціни.') + '</p>' +
      '<span class="origin-pill">' + (source ? 'JEV — окрема AI-модель' : 'Попередній аналіз кадру') + '</span></div>' +
      '<details><summary>Що видно на графіку</summary><p>' + safe(r.visual_evidence || 'Опису кадру немає.') +
      '</p><p>' + safe(r.price_action || 'Price action не визначено.') + '</p></details>' +
      '<details><summary>Обмеження та достовірність</summary><p>' +
      safe(limit.join(' • ') || 'Без незалежної перевірки котирувань.') +
      '</p><p>' + (source ? 'JEV пояснив саме дані з кадру; це не означає незалежного підтвердження угоди.' :
        'Окремий AI-висновок JEV ще не отриманий; показано лише пояснення витягнутого кадру.') +
      '</p></details><p class="report-notice">⚠ WAIT / OBSERVE · Інформаційний аналіз, не підтверджений торговий сигнал.</p>' +
      '<div class="report-actions">' +
      '<button type="button" data-act="vote" data-vote="good" data-id="' + safe(rid) + '" class="' + (vote === 'good' ? 'on' : '') + '">👍 Корисно</button>' +
      '<button type="button" data-act="vote" data-vote="bad" data-id="' + safe(rid) + '" class="' + (vote === 'bad' ? 'on' : '') + '">👎 Не корисно</button>' +
      '<button type="button" data-act="save" data-id="' + safe(rid) + '" class="' + (save ? 'on' : '') + '">' + (save ? '✓ Збережено' : '☆ Зберегти') + '</button>' +
      (savedMode ? '<button type="button" data-act="delete" data-id="' + safe(rid) + '">✕ Видалити</button>' : '') +
      video + '</div></article>';
  }
  function demoReport() {
    // The user's supplied screenshot is illustrative, not current market data.
    return {
      pair:'AUD/CNY OTC',
      instrument_type:'OTC (приклад зі скріншота)',
      observed_at:'2026-10-09T19:16:00+00:00',
      channel:'Демонстраційний приклад ChartLens',
      trend:'downtrend',volatility:'normal',volume:'unknown',
      sentiment:'bearish',confidence:'low',
      support_levels:['1.84200'],resistance_levels:['1.84400'],
      observations_count:1,
      visual_evidence:'Приклад спирається на текст зі скріншота користувача, а не на трансляцію, яку прочитала Мишка.',
      price_action:'У наданому прикладі йдеться про нижчі максимуми та мінімуми.',
      limitations:['Демо з чужого звіту, не LIVE','Поточні ціни та обсяг не перевірено','Не використовувати рівні для угоди'],
      jev:{
        engine:'demo_reference_only',status:'demo',
        why:'На демонстраційному звіті зазначено спадний рух і нижчі максимуми. JEV цього графіка самостійно не перевіряв.',
        key_levels:'1.84200 та 1.84400 — цифри з наданого прикладу, не актуальні котирування.',
        watch_next:'Для справжнього аналізу потрібен доступний LIVE-кадр, читабельна пара й незалежна перевірка рівнів.'
      }
    };
  }
  function renderDemo() {
    const node=document.createElement('div');
    node.innerHTML=reportMarkup(demoReport());
    const actions=node.querySelector('.report-actions');
    if(actions)actions.remove();
    const source=node.querySelector('.origin-pill');
    if(source)source.textContent='DEMO · OTC';
    return '<div class="demo-banner">◈ ДЕМОНСТРАЦІЯ ІНТЕРФЕЙСУ · НЕ РЕАЛЬНИЙ LIVE-АНАЛІЗ І НЕ ТОРГОВИЙ СИГНАЛ</div>'+node.innerHTML;
  }
  function renderAnalysis() {
    const reports = findReports();
    const search = state.query.toLowerCase();
    const filtered = reports.filter(r =>
      (!search || str(r.pair).toLowerCase().includes(search) ||
        str(r.channel).toLowerCase().includes(search)) &&
      (state.selectedPair == null || r.pair === state.selectedPair));
    const names = Array.from(new Set(reports.map(x => x.pair).filter(Boolean))).slice(0,40);
    $('pair-chips').innerHTML = reports.length ?
      '<button type="button" class="chip ' + (state.selectedPair == null ? 'selected' : '') +
      '" data-pair="all">Усі (' + reports.length + ')</button>' +
      names.map(x => '<button type="button" class="chip ' + (state.selectedPair === x ? 'selected' : '') +
        '" data-pair="' + safe(x) + '">' + safe(x) + '</button>').join('') : '';
    $('demo-button').textContent = state.demo ? '✕ Приховати приклад' : '◈ Показати приклад звіту';
    $('analysis-list').innerHTML = state.demo
      ? renderDemo()
      : filtered.length
        ? filtered.map(x => reportMarkup(x)).join('')
        : empty('📈', reports.length ? 'Не знайдено відповідної пари' : 'Немає опублікованих звітів',
          reports.length ? 'Зміни назву в пошуку або прибери фільтр.' :
          'Мишка поки не отримала доступних для читання кадрів. Без них неможливо обґрунтувати тренд, рівні чи прогноз.',
          null);
  }
  function renderHistory() {
    const saved = Object.entries(state.prefs.saved).map(([id, report]) => ({ id, report }))
      .filter(x => x.report && typeof x.report === 'object')
      .sort((a, b) => (timeMs(b.report.observed_at) || 0) - (timeMs(a.report.observed_at) || 0));
    $('saved-count').textContent = saved.length + ' збережено';
    $('history-list').innerHTML = saved.length ? saved.map(({ id, report }) =>
      '<article class="saved-card"><div><strong>' + safe(report.pair || 'Невідома пара') +
      '</strong><small>' + safe(formatted(report.observed_at)) + ' · ' +
      safe(I18N.trend[report.trend] || 'Тренд невідомий') + ' · ' +
      safe(report.channel || 'невідомий автор') +
      '</small></div><div class="saved-actions"><button type="button" data-act="open" data-id="' +
      safe(id) + '">Відкрити</button><button type="button" data-act="delete" data-id="' +
      safe(id) + '">Видалити</button></div></article>').join('') :
      empty('☆', 'Немає збережених звітів', 'У Fast Analysis натисни «Зберегти», щоб переглядати звіт пізніше.', 'analysis');
  }
  function renderSettings() {
    $('theme-select').value = state.prefs.theme;
    $('refresh-select').value = String(state.prefs.refresh);
    const line = (label, value) => '<div class="health-row"><span>' + safe(label) + '</span><b>' + safe(value) + '</b></div>';
    const stateLine = name => state.statuses[name] === 'error' ? 'Помилка завантаження' :
      state.statuses[name] === 'ok' ? 'Дані отримано' : 'Очікування';
    const live = state.live || {};
    const last = live.updated_at ? formatted(live.updated_at) : 'Невідомо';
    $('data-health').innerHTML =
      line('Трансляції', stateLine('live')) +
      line('Картки аналізу', stateLine('pairs')) +
      line('YouTube-аналітики', stateLine('analysts')) +
      line('Час останньої публікації', last) +
      line('Дані актуальні', fresh(live.updated_at) ? 'Так, за часом публікації' : 'Ні / невідомо') +
      line('AI читання кадрів', live.ai_enabled ? 'Налаштовано (не гарантує доступ)' : 'Не налаштовано') +
      line('Режим', 'Без автоматичних угод');
  }
  function renderView() {
    if (state.view === 'home') renderHome();
    else if (state.view === 'analysis') renderAnalysis();
    else if (state.view === 'history') renderHistory();
    else renderSettings();
  }
  function renderAll() { statusPill(); renderView(); }
  function findReportById(id) {
    return findReports().find(x => key(x) === id) || state.prefs.saved[id] || null;
  }
  function reportAction(action, id, value) {
    const record = findReportById(id);
    if (action === 'vote' && record && ['good', 'bad'].includes(value)) {
      if (state.prefs.votes[id] === value) delete state.prefs.votes[id];
      else state.prefs.votes[id] = value;
      persist(); toast('Оцінку збережено на цьому пристрої');
    } else if (action === 'save' && record) {
      if (own(state.prefs.saved, id)) {
        delete state.prefs.saved[id]; toast('Звіт прибрано зі збережених');
      } else {
        const clone = JSON.parse(JSON.stringify(record));
        state.prefs.saved[id] = clone;
        if (Object.keys(state.prefs.saved).length > 100) {
          const old = Object.keys(state.prefs.saved)[0];
          delete state.prefs.saved[old];
        }
        toast('Звіт збережено');
      }
      persist();
    } else if (action === 'delete') {
      if (!own(state.prefs.saved, id)) return;
      if (!window.confirm('Видалити цей звіт із пам’яті браузера?')) return;
      delete state.prefs.saved[id]; persist(); toast('Звіт видалено');
    } else if (action === 'open' && record) {
      state.query = '';
      $('pair-search').value = '';
      state.selectedPair = record.pair || null;
      navigate('analysis');
      // If source no longer includes the historical report, show the saved copy.
      if (!findReports().some(x => key(x) === id)) {
        $('analysis-list').innerHTML = reportMarkup(record, true);
        $('pair-chips').innerHTML = '<span class="chip selected">Збережений знімок · не LIVE</span>';
      }
      return;
    } else { return; }
    renderAnalysis(); renderHistory();
  }
  const DEMO_OUTCOMES_KEY = 'crypto-myshka-demo-expiry-v1';
  function demoOutcomes() {
    try {
      const records = JSON.parse(localStorage.getItem(DEMO_OUTCOMES_KEY) || '[]');
      return arr(records).filter(r => r && [30, 60, 300].includes(r.expiry) &&
        typeof r.correct === 'boolean' && typeof r.id === 'string').slice(-500);
    } catch { return []; }
  }
  function updateDemoJournal() {
    const summary = $('expiry-journal-summary');
    if (!summary) return;
    const records = demoOutcomes();
    if (!records.length) {
      summary.textContent = 'Поки немає позначених деморезультатів.';
      return;
    }
    const buckets = [30, 60, 300].map(expiry => {
      const subset = records.filter(r => r.expiry === expiry);
      const hits = subset.filter(r => r.correct).length;
      const label = expiry === 30 ? '30 с' : expiry === 60 ? '1 хв' : '5 хв';
      return label + ': ' + hits + '/' + subset.length +
        (subset.length >= 30 ? ' (' + Math.round(100 * hits / subset.length) + '%)' : ' (мала вибірка)');
    });
    summary.textContent = 'Демо, позначено вручну: ' + records.length + ' · ' + buckets.join(' · ');
  }
  function recordDemoOutcome(id, expiry, action, correct) {
    const records = demoOutcomes();
    if (records.some(r => r.id === id)) return false;
    records.push({id, expiry, action, correct, at: new Date().toISOString()});
    try {
      localStorage.setItem(DEMO_OUTCOMES_KEY, JSON.stringify(records.slice(-500)));
      updateDemoJournal();
      return true;
    } catch {
      toast('Браузер не дозволив зберегти деморезультат.');
      return false;
    }
  }
  function imageFingerprint(dataUrl, action, expiry, timeframe) {
    // Privacy: persist only a short fingerprint, never screenshot bytes.
    let hash = 2166136261;
    const step = Math.max(1, Math.floor(dataUrl.length / 1024));
    for (let i = 0; i < dataUrl.length; i += step) {
      hash = Math.imul(hash ^ dataUrl.charCodeAt(i), 16777619);
    }
    return [hash >>> 0, dataUrl.length, action, expiry, timeframe].join(':');
  }
  async function checkVisionHealth() {
    const status = $('vision-status');
    if (!status) return;
    const local = ['localhost', '127.0.0.1'].includes(location.hostname);
    state.visionStatus = 'checking';
    state.visionSource = null;
    status.dataset.ready = 'false';
    status.textContent = '⏳ Перевіряємо JEV…';
    statusPill();
    if (local) {
      try {
        const response = await fetch('./api/chart-health', {cache:'no-store'});
        const result = response.ok ? await response.json() : {};
        if (result.ready) {
          state.visionStatus = 'ready';
          state.visionSource = 'local';
          status.dataset.ready = 'true';
          status.textContent = '🟢 JEV готовий · модель ' + result.model + ' · локальна Ollama';
          statusPill();
          updateCloudSettings();
          if (state.view === 'home') renderHome();
          return;
        }
        if (result.ollama && !state.cloudEndpoint) {
          state.visionStatus = 'missing_model';
          status.textContent = '🟠 Ollama працює, але модель відсутня: ollama pull ' + result.model;
        }
      } catch { /* Cloud may still be configured as a fallback. */ }
    }
    if (state.cloudEndpoint && state.cloudAccess) {
      try {
        const response = await fetch(state.cloudEndpoint + '/api/chart-health', {
          cache:'no-store', headers:{'X-JEV-Access':state.cloudAccess}
        });
        const result = await response.json();
        if (!response.ok || !result.ready) throw new Error(result.error || 'HTTP ' + response.status);
        state.visionStatus = 'ready';
        state.visionSource = 'cloud';
        status.dataset.ready = 'true';
        status.textContent = '🟢 JEV готовий · ' + (result.model || 'Gemini') + ' · хмарний сервер';
      } catch (error) {
        state.visionStatus = 'offline';
        status.textContent = '🔴 Хмарний JEV не готовий: ' + (error.message || 'Перевір URL, код і секрети Vercel.');
      }
    } else if (!local) {
      state.visionStatus = 'offline';
      status.textContent = state.cloudEndpoint ?
        '🟠 Введи код доступу в Налаштуваннях для хмарного JEV.' :
        '🟠 Хмарний JEV не підключено. Відкрий Налаштування → Хмарний JEV.';
    } else if (state.visionStatus === 'checking') {
      state.visionStatus = 'offline';
      status.textContent = '🔴 Локальна Ollama не відповідає. Запусти START_MYSHKA_AI.ps1 або підключи хмарний JEV.';
    }
    statusPill();
    updateCloudSettings();
    if (state.view === 'home') renderHome();
  }

  function installInteractions() {
    document.body.addEventListener('click', e => {
      const go = e.target.closest('button[data-go]');
      if (go) { navigate(go.dataset.go); return; }
      const pair = e.target.closest('button[data-pair]');
      if (pair) { state.selectedPair = pair.dataset.pair === 'all' ? null : pair.dataset.pair; renderAnalysis(); return; }
      const act = e.target.closest('button[data-act]');
      if (act) { reportAction(act.dataset.act, act.dataset.id, act.dataset.vote); }
    });
    // Screenshot analysis is local by default. Cloud mode is opt-in with a private
    // Vercel backend and a session-only access code; no API keys in this browser.
    let imageRequestId = 0;
    const analyzeChartImage = file => {
      if (!file) return;
      const requestId = ++imageRequestId;
      const box = $('photo-analysis');
      if (!['image/jpeg', 'image/png', 'image/webp'].includes(file.type) ||
          file.size < 1 || file.size > 8 * 1024 * 1024) {
        box.textContent = 'Потрібен JPG, PNG або WebP до 8 МБ.';
        return;
      }
      box.textContent = '📷 Читаємо скріншот…';
      const reader = new FileReader();
      reader.onerror = () => {
        if (requestId === imageRequestId) box.textContent = 'Не вдалося прочитати файл.';
      };
      reader.onload = () => {
        if (requestId !== imageRequestId) return;
        const dataUrl = reader.result;
        if (typeof dataUrl !== 'string' || !/^data:image\/(?:png|jpeg|webp);base64,/.test(dataUrl)) {
          box.textContent = 'Формат фото не підтримується.';
          return;
        }
        const image = new Image();
        image.onerror = () => {
          if (requestId === imageRequestId) box.textContent = 'Файл не є коректним зображенням.';
        };
        image.onload = () => {
          if (requestId !== imageRequestId) return;
          const info = document.createElement('div');
          info.className = 'report-card photo-report';
          const preview = document.createElement('img');
          preview.className = 'chart-photo-preview';
          preview.alt = 'Завантажений графік: ' + file.name;
          preview.src = dataUrl;
          const fileLabel = document.createElement('p');
          fileLabel.className = 'chart-photo-filename';
          fileLabel.textContent = '📎 ' + file.name + ' · ' + image.width + ' × ' + image.height + ' px';
          const heading = document.createElement('h3');
          heading.textContent = '📷 Скріншот графіка';
          const note = document.createElement('p');
          note.className = 'report-notice';
          note.textContent = 'Оригінальна роздільність збережена. Хмарний режим передає фото на твій сервер та до Gemini. Зі скріншота не можна підтвердити майбутню ціну чи результат угоди.';
          const aiArea = document.createElement('div');
          aiArea.className = 'jev-image-area';
          const aiButton = document.createElement('button');
          aiButton.type = 'button';
          aiButton.className = 'small-button';
          aiButton.textContent = '🤖 Повторити аналіз JEV';
          const aiResult = document.createElement('div');
          aiResult.className = 'jev-image-result';
          aiResult.setAttribute('role', 'status');
          aiResult.setAttribute('aria-live', 'polite');
          const localServer = ['localhost', '127.0.0.1'].includes(location.hostname);
          if (!localServer && !(state.cloudEndpoint && state.cloudAccess)) {
            aiButton.disabled = true;
            aiResult.textContent = '⛔ Хмарний JEV ще не підключено. Відкрий Налаштування → Хмарний JEV. Або скористайся локальною Ollama.';
          } else {
            aiResult.textContent = 'Перевіряємо доступність JEV…';
            aiButton.addEventListener('click', async () => {
              if (requestId !== imageRequestId) return;
              aiButton.disabled = true;
              const analysisStartedAt = Date.now();
              aiResult.className = 'jev-image-result';
              aiResult.textContent = '⏳ Перевіряємо AI-сервер…';
              try {
                const useCloud = state.visionSource === 'cloud' ||
                  (!localServer && !!state.cloudEndpoint);
                if (useCloud && !state.cloudAccess) throw new Error('Введи код доступу до хмарного JEV у Налаштуваннях.');
                if (useCloud && file.size > 2 * 1024 * 1024) throw new Error('Хмарний JEV приймає фото до 2 МБ. Обріж або стисни скріншот.');
                const apiRoot = useCloud ? state.cloudEndpoint : '.';
                const authHeaders = useCloud ? {'X-JEV-Access':state.cloudAccess} : {};
                const healthResponse = await fetch(apiRoot + '/api/chart-health', {
                  cache:'no-store', headers:authHeaders
                });
                const health = await healthResponse.json();
                if (!healthResponse.ok || !health.ready) {
                  if (useCloud) throw new Error(health.error || 'Хмарний JEV недоступний. Перевір Vercel та код доступу.');
                  if (!health.ollama) throw new Error('Ollama не відповідає. Запусти Ollama або ollama serve.');
                  throw new Error('Модель не встановлена. Виконай: ollama pull ' + (health.model || 'qwen2.5vl:3b'));
                }
                if (requestId !== imageRequestId) return;
                aiResult.textContent = '⏳ JEV читає свічки на скріншоті…';
                const response = await fetch(apiRoot + '/api/chart-analysis', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json', ...authHeaders},
                  body: JSON.stringify({image: dataUrl.split(',')[1], chart_timeframe: $('chart-timeframe').value})
                });
                const result = await response.json();
                if (!response.ok) throw new Error(result.error || 'Помилка AI-сервера (HTTP ' + response.status + ')');
                if (requestId !== imageRequestId) return;
                const direction = ['ВГОРУ', 'ВНИЗ', 'НЕВИЗНАЧЕНО'].includes(result.direction)
                  ? result.direction : 'НЕВИЗНАЧЕНО';
                const proposedAction = ['BUY', 'SELL'].includes(result.action) ? result.action : 'SKIP';
                const expiry = [30, 60, 300].includes(result.test_expiry_seconds)
                  ? result.test_expiry_seconds : null;
                const elapsed = Math.round((Date.now() - analysisStartedAt) / 1000);
                const validAction = expiry !== null && proposedAction !== 'SKIP' &&
                  (proposedAction === 'BUY' ? direction === 'ВГОРУ' : direction === 'ВНИЗ');
                const tooLate = validAction && elapsed >= expiry;
                const action = validAction && !tooLate ? proposedAction : 'SKIP';
                const durationLabel = seconds => seconds === 30 ? '30 секунд' :
                  seconds === 60 ? '1 хвилина' : seconds === 300 ? '5 хвилин' : 'Не визначено';
                const tfLabel = tf => ({'15s': '15 с', '30s': '30 с', '1m': '1 хв', '5m': '5 хв'})[tf] || 'не визначено';
                const makeLine = (tag, cls, value) => {
                  const el = document.createElement(tag);
                  if (cls) el.className = cls;
                  el.textContent = value;
                  return el;
                };
                aiResult.className = 'jev-image-result ' +
                  (action === 'BUY' ? 'direction-up' : action === 'SELL' ? 'direction-down' : 'direction-neutral');
                const heading = action === 'BUY' ? 'ДЕМО-ГІПОТЕЗА: BUY ↑' :
                  action === 'SELL' ? 'ДЕМО-ГІПОТЕЗА: SELL ↓' : 'ПРОПУСТИТИ — сигнал не підтверджено';
                const title = makeLine('div', 'direction-result', heading);
                const visible = makeLine('p', 'jev-image-meta', 'Видимий рух: ' +
                  (direction === 'ВГОРУ' ? '↑ ВГОРУ' : direction === 'ВНИЗ' ? '↓ ВНИЗ' : '— НЕВИЗНАЧЕНО'));
                const tfSource = result.timeframe_source === 'user' ? 'заданий вручну' :
                  result.timeframe_source === 'model' ? 'оцінений AI, не перевірено' : 'не визначено';
                const timeframe = makeLine('p', 'jev-image-meta',
                  'Таймфрейм свічок: ' + tfLabel(result.chart_timeframe) + ' (' + tfSource + ')');
                const testTime = makeLine('p', 'jev-image-expiry',
                  action === 'SKIP' ? 'Час закриття: не рекомендовано' :
                    'Експериментальний час закриття: ' + durationLabel(expiry));
                const reason = makeLine('p', 'jev-image-reason', 'Підстава: ' +
                  (typeof result.reason === 'string' ? result.reason.slice(0, 220) : 'Недостатньо інформації.'));
                const latency = makeLine('p', 'jev-image-meta',
                  'Обробка: ' + elapsed + ' с. Фото не є живим потоком котирувань.');
                const warning = makeLine('p', 'report-notice',
                  tooLate ? '⛔ Аналіз тривав довше за тестову експірацію. Пропустити.' :
                    '⚠️ Це неперевірена гіпотеза для демо, а не команда на ставку. OTC-котирування не звірені.' +
                    (useCloud ? ' Фото оброблено хмарним AI.' : ' Фото оброблено локально.'));
                aiResult.replaceChildren(title, visible, timeframe, testTime, reason, latency, warning);
                if (action !== 'SKIP') {
                  const outcomeId = imageFingerprint(dataUrl, action, expiry, result.chart_timeframe);
                  const outcomeRow = document.createElement('div');
                  outcomeRow.className = 'expiry-outcome-row';
                  const outcomeTitle = makeLine('span', 'jev-image-meta',
                    'Після завершення демоугоди познач результат вручну:');
                  const hit = makeLine('button', 'small-button', '✓ Демо: влучив');
                  const miss = makeLine('button', 'small-button', '✕ Демо: помилився');
                  hit.type = 'button';
                  miss.type = 'button';
                  const save = correct => {
                    if (!recordDemoOutcome(outcomeId, expiry, action, correct)) {
                      toast('Цей скріншот уже є в деможурналі або запис недоступний.');
                      return;
                    }
                    hit.disabled = true;
                    miss.disabled = true;
                    outcomeTitle.textContent = 'Деморезультат записано локально (без перевірки брокером).';
                  };
                  hit.addEventListener('click', () => save(true));
                  miss.addEventListener('click', () => save(false));
                  if (demoOutcomes().some(r => r.id === outcomeId)) {
                    hit.disabled = true;
                    miss.disabled = true;
                    outcomeTitle.textContent = 'Цей скріншот уже позначено в деможурналі.';
                  }
                  outcomeRow.append(outcomeTitle, hit, miss);
                  aiResult.append(outcomeRow);
                }
              } catch (error) {
                if (requestId === imageRequestId) {
                  aiResult.className = 'jev-image-result';
                  aiResult.textContent = '⚠️ ' + (error && error.message ? error.message : 'Не вдалося зв’язатися з JEV.');
                }
              } finally {
                if (requestId === imageRequestId) aiButton.disabled = false;
              }
            });
          }
          aiArea.append(aiButton, aiResult);
          info.append(preview, fileLabel, heading, note, aiArea);
          box.replaceChildren(info);
          if (localServer) aiButton.click();
        };
        image.src = dataUrl;
      };
      reader.readAsDataURL(file);
    };
    $('chart-photo').addEventListener('change', event => {
      const file = event.target.files && event.target.files[0];
      analyzeChartImage(file);
      event.target.value = '';
    });
    // Windows Snipping Tool -> Ctrl+V directly on the Analysis screen.
    document.addEventListener('paste', event => {
      if (state.view !== 'analysis') return;
      const active = document.activeElement;
      if (active && active.matches('input, textarea, [contenteditable="true"]')) return;
      const clipboard = event.clipboardData;
      if (!clipboard) return;
      const item = Array.from(clipboard.items || []).find(entry =>
        entry.kind === 'file' && entry.type.startsWith('image/'));
      const file = item ? item.getAsFile() :
        Array.from(clipboard.files || []).find(entry => entry.type.startsWith('image/'));
      if (!file) return;
      event.preventDefault();
      analyzeChartImage(file);
    });
    $('refresh-button').addEventListener('click', () => { refreshAll(true); checkVisionHealth(); });
    $('demo-button').addEventListener('click', () => {
      state.demo = !state.demo;
      renderAnalysis();
    });
    $('pair-search').addEventListener('input', e => {
      state.query = e.target.value.trim();
      state.selectedPair = null;
      renderAnalysis();
    });
    $('cloud-connect').addEventListener('click', async () => {
      const endpoint = validCloudEndpoint($('cloud-endpoint').value);
      const access = $('cloud-access').value.trim();
      if (!endpoint || access.length < 24) {
        $('cloud-connection-status').textContent = 'Потрібна коректна HTTPS-адреса без шляху та код доступу не коротший за 24 символи.';
        return;
      }
      state.cloudEndpoint = endpoint;
      state.cloudAccess = access;
      try {
        localStorage.setItem(CLOUD_URL_KEY, endpoint);
        sessionStorage.setItem(CLOUD_ACCESS_KEY, access);
      } catch { toast('Сховище браузера недоступне. Параметри діють лише до оновлення.'); }
      await checkVisionHealth();
      if (state.visionSource === 'cloud' && state.visionStatus === 'ready') toast('Хмарний JEV підключено.');
      else toast('Хмарний JEV не підтверджено. Перевір адресу, код і секрети сервера.');
    });
    $('cloud-disconnect').addEventListener('click', () => {
      state.cloudEndpoint = '';
      state.cloudAccess = '';
      $('cloud-endpoint').value = '';
      $('cloud-access').value = '';
      try { localStorage.removeItem(CLOUD_URL_KEY); sessionStorage.removeItem(CLOUD_ACCESS_KEY); } catch {}
      checkVisionHealth();
      toast('Хмарний JEV від’єднано.');
    });
    $('theme-select').addEventListener('change', e => {
      if (allowedTheme.has(e.target.value)) { state.prefs.theme = e.target.value; persist(); applyTheme(); }
    });
    $('refresh-select').addEventListener('change', e => {
      const sec = Number(e.target.value);
      if (!allowedRefresh.has(sec)) return;
      state.prefs.refresh = sec; persist(); startPolling();
      toast('Оновлення інтерфейсу кожні ' + sec + ' секунд');
    });
    window.addEventListener('hashchange', () => navigate(routeView(), { fromHash: true }));
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) refreshAll();
    });
  }
  function startPolling() {
    if (state.pollTimer) clearInterval(state.pollTimer);
    state.pollTimer = setInterval(() => { if (!document.hidden) refreshAll(); }, state.prefs.refresh * 1000);
  }
  function boot() {
    loadPrefs();
    loadCloudSettings();
    applyTheme();
    installInteractions();
    navigate(routeView(), { fromHash: true, noScroll: true });
    refreshAll();
    checkVisionHealth();
    updateDemoJournal();
    startPolling();
    if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
      if (['localhost', '127.0.0.1'].includes(location.hostname)) {
        // Old localhost PWA registrations may serve outdated app files.
        navigator.serviceWorker.getRegistrations().then(registrations =>
          Promise.all(registrations.filter(reg => reg.scope.startsWith(location.origin + '/'))
            .map(reg => reg.unregister()))).catch(() => {});
      } else {
        navigator.serviceWorker.register('./myshka-sw.js').catch(() => {});
      }
    }
  }
  boot();
})();
