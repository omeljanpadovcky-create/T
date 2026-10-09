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
  const VIEWS = new Set(['home', 'live', 'analysis', 'history', 'settings']);
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
    selectedPair: null, refreshing: false, sequence: 0,
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
  function applyTheme() {
    document.documentElement.dataset.theme = state.prefs.theme;
    document.querySelector('meta[name="theme-color"]').content =
      state.prefs.theme === 'dark' ? '#0b111d' : '#f6f8fc';
    $('theme-select').value = state.prefs.theme;
    $('refresh-select').value = String(state.prefs.refresh);
  }
  function routeView() {
    const hash = location.hash.replace(/^#/, '').toLowerCase();
    return VIEWS.has(hash) ? hash : 'home';
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
    const names = { home: 'AI Chart Observer', live: 'LIVE Monitor', analysis: 'Fast Analysis', history: 'Збережене', settings: 'Налаштування' };
    $('top-context').textContent = names[to];
    document.title = names[to] + ' · Crypto Myshka';
    if (!options.fromHash) history.replaceState(null, '', location.pathname + location.search + '#' + to);
    renderView();
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
    const ok = state.statuses.live === 'ok' && state.statuses.pairs === 'ok';
    const upToDate = state.live && fresh(state.live.updated_at);
    node.className = 'connection-pill ' + (ok && upToDate ? 'good' : 'warn');
    node.innerHTML = '<span class="dot"></span> ' +
      (ok && upToDate ? 'Дані отримано' : ok ? 'Архівні дані' : 'Немає зв’язку з джерелами');
  }
  function renderHome() {
    const live = state.live || {};
    const channels = arr(live.channels);
    const recent = fresh(live.updated_at);
    $('stat-channels').textContent = channels.length ? String(channels.length) : '—';
    $('stat-live').textContent = recent ? String(channels.filter(x => x.live === true && x.status === 'LIVE' && fresh(x.checked_at, 3)).length) : '—';
    const reports = findReports();
    $('stat-pairs').textContent = String(reports.length);
    const engines = reports.filter(r => r.jev && r.jev.engine === 'separate_ai_explainer' && r.jev.status === 'model');
    $('stat-jev').textContent = engines.length ? 'AI ✓' : 'Очікує';
    const notice = $('home-notice').querySelector('p');
    const errors = Object.values(state.statuses).filter(x => x === 'error').length;
    if (errors) {
      notice.textContent = 'Не всі джерела завантажилися. Перевір інтернет, потім натисни ↻. Старий сайт працює окремо.';
    } else if (!reports.length) {
      notice.textContent = 'Поки немає прочитаних LIVE-графіків. Сторінка не створюватиме вигаданих прогнозів, навіть коли YouTube недоступний.';
    } else {
      notice.textContent = 'Дані графіків — спостереження, а не перевірені угоди. Для OTC потрібна особлива обережність із котируваннями.';
    }
  }
  function renderLive() {
    const live = state.live || {};
    const channels = arr(live.channels);
    const recent = fresh(live.updated_at);
    const confirmedLive = recent ? channels.filter(x => x.live === true && x.status === 'LIVE' && fresh(x.checked_at, 3)).length : 0;
    $('live-cadence').textContent = live.scan_interval_seconds ? 'Сканування ' + live.scan_interval_seconds + ' с (локально)' : '~5 хв у GitHub';
    $('live-summary').textContent = recent ? (confirmedLive ? 'Підтверджено LIVE: ' + confirmedLive : 'Активний LIVE не підтверджено') : 'Немає актуального підтвердження LIVE';
    $('live-timestamp').textContent = live.updated_at ? 'Дані: ' + formatted(live.updated_at) : 'Перший звіт очікується';
    const box = $('live-list');
    if (!channels.length) {
      box.innerHTML = empty('📡', 'Канали поки не завантажені', 'Знайдені канали з’являться тут, коли монітор опублікує звіт.');
      return;
    }
    box.innerHTML = channels.map(channel => {
      const online = recent && channel.live === true && channel.status === 'LIVE' && fresh(channel.checked_at, 3);
      const unverified = channel.status === 'source_unverified';
      const blocked = channel.status === 'access_blocked' || channel.status === 'check_error';
      const label = online ? '🔴 LIVE' : blocked ? '⚠ Недоступний' : unverified ? 'Потрібен URL' :
        channel.status === 'not_detected' ? 'LIVE не підтверджено' : 'Немає актуальних даних';
      const pill = online ? 'live' : unverified ? 'off' : '';
      const stream = channel.stream || {};
      const url = stream.url || channel.live_page ||
        (channel.handle ? 'https://www.youtube.com/' + channel.handle + '/live' : null);
      const recentObservations = arr(live.observations).filter(x => x.channel_id === channel.id);
      const lastObservation = recentObservations[recentObservations.length - 1];
      const pair = lastObservation && lastObservation.observation && lastObservation.observation.asset;
      const checked = channel.checked_at ? formatted(channel.checked_at) : 'Невідомо';
      const details = channel.observation_status === 'visual_claim_reviewed' ? 'Кадр розпізнано' :
        channel.observation_status === 'requires_OPENAI_API_KEY_or_local_OLLAMA' ? 'AI-читання не налаштовано' :
        channel.observation_status === 'frame_unavailable' ? 'Кадр не вдалося отримати' :
        channel.observation_status === 'media_unavailable' ? 'Відеопотік недоступний' :
        channel.observation_status === 'analysis_unavailable' ? 'AI-аналіз не відповів' :
        'Немає підтвердженого аналізу кадру';
      return '<article class="stream-card"><div class="stream-main"><h3>' + safe(channel.name || 'Невідомий канал') +
        '</h3><small>' + safe(channel.handle || 'Без підтвердженого посилання') +
        '</small></div><span class="stream-status ' + pill + '">' + label +
        '</span><div class="stream-detail"><span>Остання перевірка: <b>' + safe(checked) +
        '</b></span><span>Пара: <b>' + safe(pair && fresh(lastObservation.observed_at, 15) ? pair : 'Не визначено') +
        '</b></span><span>AI: <b>' + safe(details) +
        '</b></span></div><div class="stream-actions">' + link(url, online ? 'Дивитись LIVE' : 'Перевірити канал', 'primary-link') +
        '<button type="button" class="small-button" data-go="analysis">Перейти до аналізу →</button></div></article>';
    }).join('');
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
    $('analysis-list').innerHTML = filtered.length
      ? filtered.map(x => reportMarkup(x)).join('')
      : empty('📈', reports.length ? 'Не знайдено відповідної пари' : 'Очікуємо перший LIVE-аналіз',
        reports.length ? 'Зміни назву в пошуку або прибери фільтр.' :
        'Мишка поки не отримала доступних для читання кадрів. Без них неможливо обґрунтувати тренд, рівні чи прогноз.',
        reports.length ? null : 'live');
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
    else if (state.view === 'live') renderLive();
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
  function installInteractions() {
    document.body.addEventListener('click', e => {
      const go = e.target.closest('button[data-go]');
      if (go) { navigate(go.dataset.go); return; }
      const pair = e.target.closest('button[data-pair]');
      if (pair) { state.selectedPair = pair.dataset.pair === 'all' ? null : pair.dataset.pair; renderAnalysis(); return; }
      const act = e.target.closest('button[data-act]');
      if (act) { reportAction(act.dataset.act, act.dataset.id, act.dataset.vote); }
    });
    $('refresh-button').addEventListener('click', () => refreshAll(true));
    $('pair-search').addEventListener('input', e => {
      state.query = e.target.value.trim();
      state.selectedPair = null;
      renderAnalysis();
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
    applyTheme();
    installInteractions();
    navigate(routeView(), { fromHash: true, noScroll: true });
    refreshAll();
    startPolling();
    if ('serviceWorker' in navigator && /^https?:$/.test(location.protocol)) {
      navigator.serviceWorker.register('./myshka-sw.js').catch(() => {});
    }
  }
  boot();
})();
