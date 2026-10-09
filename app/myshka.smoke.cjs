/* Run with node app/myshka.smoke.cjs (requires jsdom). No external API requests. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

(async () => {
  const root = path.resolve(__dirname, '..');
  const html = fs.readFileSync(path.join(root, 'myshka-app.html'), 'utf8');
  const js = fs.readFileSync(path.join(root, 'app/myshka.js'), 'utf8');
  const live = {
    updated_at: new Date().toISOString(), scan_interval_seconds: 15,
    channels: [
      { id: 'nikolas', name: 'НИКОЛАС | ТРЕЙДЕР', handle: '@NikolasTradin',
        status: 'not_detected', live: false, checked_at: new Date().toISOString(),
        live_page: 'https://www.youtube.com/@NikolasTradin/live' },
      { id: 'unknown', name: 'Невизначений канал', status: 'source_unverified', live: false }
    ],
    observations: [], ai_enabled: false
  };
  const now = new Date().toISOString();
  const reports = {
    updated_at: now, reports: [
      { pair: 'AUD/CNY OTC', instrument_type: 'OTC (брокерські котирування)',
        observed_at: now, channel: 'НИКОЛАС | ТРЕЙДЕР', trend: 'downtrend',
        volatility: 'normal', volume: 'unknown', sentiment: 'bearish', confidence: 'low',
        support_levels: ['1.84200'], resistance_levels: ['1.84400'],
        visual_evidence: 'Свічки та рівні на кадрі', price_action: 'Видно нижчі максимуми',
        observations_count: 1, jev: {
          engine: 'separate_ai_explainer', status: 'model', provider: 'ollama',
          why: 'На кадрі видно кілька нижчих максимумів.',
          key_levels: 'Цифри з кадру; котирування не звірені.',
          watch_next: 'Перевірити наступні свічки.'
        }, limitations: ['Без незалежного підтвердження котирувань'] }
    ]
  };
  const analysts = { channels: [
    { name: 'НИКОЛАС | ТРЕЙДЕР', confirmed: true },
    { name: 'Невизначений канал', confirmed: false }
  ] };
  const data = { 'youtube_live.json': live, 'pair_reports.json': reports, 'youtube_analysts.json': analysts };
  const dom = new JSDOM(html, {
    url: 'https://example.org/T/myshka-app.html',
    pretendToBeVisual: true, runScripts: 'outside-only'
  });
  const win = dom.window;
  win.scrollTo = () => {};
  win.fetch = async url => {
    const filename = String(url).split('/').pop().split('?')[0];
    if (!data[filename]) throw Error('Unexpected resource: ' + url);
    return { ok: true, json: async () => data[filename] };
  };
  win.eval(js);
  await new Promise(resolve => setTimeout(resolve, 180));
  const doc = win.document;
  const click = selector => {
    const el = doc.querySelector(selector);
    assert.ok(el, 'Missing control: ' + selector);
    el.click();
    return el;
  };
  assert.equal(doc.querySelectorAll('.bottom-nav button').length, 4, 'four remaining mobile screens');
  assert.equal(doc.querySelector('#screen-live'), null, 'LIVE Monitor screen must be removed');
  assert.equal(doc.querySelector('[data-go="live"]'), null, 'LIVE Monitor links must be removed');
  assert.doesNotMatch(doc.querySelector('#screen-home').textContent, /НИКОЛАС|LIVE Monitor/);
  assert.equal(doc.querySelector('#stat-pairs').textContent, '1');
  assert.match(doc.querySelector('#connection-pill').textContent, /JEV тільки локально/, 'cloud header must not claim missing sources');
  click('.bottom-nav [data-go="analysis"]');
  assert.equal(doc.querySelector('#screen-analysis').hidden, false);
  assert.match(doc.querySelector('#analysis-list').textContent, /AUD\/CNY OTC/);
  assert.match(doc.querySelector('#analysis-list').textContent, /JEV — окрема AI-модель/);
  assert.match(doc.querySelector('#analysis-list').textContent, /Низька/);
  click('button[data-act="save"]');
  assert.match(doc.querySelector('#analysis-list').textContent, /Збережено/);
  click('.bottom-nav [data-go="history"]');
  assert.match(doc.querySelector('#history-list').textContent, /AUD\/CNY OTC/);
  assert.ok(Object.keys(JSON.parse(win.localStorage.getItem('crypto-myshka-app-v1')).saved).length === 1);
  click('.bottom-nav [data-go="settings"]');
  const theme = doc.querySelector('#theme-select');
  theme.value = 'dark'; theme.dispatchEvent(new win.Event('change', { bubbles: true }));
  assert.equal(doc.documentElement.dataset.theme, 'dark');
  const refresh = doc.querySelector('#refresh-select');
  refresh.value = '30'; refresh.dispatchEvent(new win.Event('change', { bubbles: true }));
  assert.equal(JSON.parse(win.localStorage.getItem('crypto-myshka-app-v1')).refresh, 30);
  // No live frame should produce a pseudo-forecast.
  data['pair_reports.json'] = { updated_at: now, reports: [] };
  click('#refresh-button');
  await new Promise(resolve => setTimeout(resolve, 150));
  click('.bottom-nav [data-go="analysis"]');
  assert.match(doc.querySelector('#analysis-list').textContent, /Немає опублікованих звітів/);
  click('#demo-button');
  assert.match(doc.querySelector('#analysis-list').textContent, /ДЕМОНСТРАЦІЯ ІНТЕРФЕЙСУ/);
  assert.match(doc.querySelector('#analysis-list').textContent, /AUD\/CNY OTC/);
  assert.equal(doc.querySelector('#analysis-list .report-actions'), null, 'demo must not offer to save or rate a fake report');
  click('#demo-button');
  assert.match(doc.querySelector('#analysis-list').textContent, /Немає опублікованих звітів/);
  // A chart photo must remain at full resolution and be shown before analysis.
  win.FileReader = class {
    readAsDataURL(_file) {
      this.result = 'data:image/png;base64,aGVsbG8=';
      this.onload();
    }
  };
  win.Image = class {
    constructor() { this.width = 1281; this.height = 602; }
    set src(_value) { this.onload(); }
  };
  const input = doc.querySelector('#chart-photo');
  Object.defineProperty(input, 'files', { configurable: true, value: [
    { name: 'market-chart.png', type: 'image/png', size: 1000 }
  ] });
  input.dispatchEvent(new win.Event('change', { bubbles: true }));
  const preview = doc.querySelector('#photo-analysis img.chart-photo-preview');
  assert.ok(preview, 'uploaded chart must be visible in analysis result');
  assert.equal(preview.src, 'data:image/png;base64,aGVsbG8=');
  assert.match(preview.alt, /market-chart.png/);
  assert.match(doc.querySelector('#photo-analysis').textContent, /1281 × 602/);
  assert.match(doc.querySelector('#vision-status').textContent, /Хмарна сторінка/);
  assert.equal(doc.querySelector('.jev-image-area button').disabled, true, 'GitHub Pages must not fake AI');

  // Local app: probe Ollama, send the full screenshot and show direction only.
  const localDom = new JSDOM(html, {
    url: 'http://127.0.0.1:18765/myshka-app.html#analysis',
    pretendToBeVisual: true, runScripts: 'outside-only'
  });
  const localWin = localDom.window;
  localWin.scrollTo = () => {};
  localWin.FileReader = win.FileReader;
  localWin.Image = win.Image;
  let healthChecks = 0, imageCalls = 0;
  localWin.fetch = async (url, opts) => {
    if (String(url).includes('/api/chart-health')) {
      healthChecks++;
      return {ok: true, json: async () => ({ready: true, ollama: true, model: 'qwen2.5vl:3b'})};
    }
    if (String(url).includes('/api/chart-analysis')) {
      imageCalls++;
      assert.equal(opts.method, 'POST');
      assert.equal(JSON.parse(opts.body).image, 'aGVsbG8=', 'full original image is sent');
      assert.equal(JSON.parse(opts.body).chart_timeframe, '1m', 'selected candle timeframe is sent');
      if (imageCalls === 1) return {ok: true, json: async () => ({
        analysis: 'ВГОРУ', direction: 'ВГОРУ', action: 'BUY', test_expiry_seconds: 60,
        chart_timeframe: '1m', timeframe_source: 'user',
        reason: 'Видно послідовність вищих мінімумів.', mode: 'demo_hypothesis'
      })};
      return {ok: true, json: async () => ({
        analysis: 'НЕВИЗНАЧЕНО', direction: 'НЕВИЗНАЧЕНО', action: 'SKIP',
        test_expiry_seconds: null, chart_timeframe: '1m', timeframe_source: 'user',
        reason: 'Рух змішаний.', mode: 'demo_hypothesis'
      })};
    }
    const filename = String(url).split('/').pop().split('?')[0];
    if (!data[filename]) throw Error('Unexpected resource: ' + url);
    return {ok: true, json: async () => data[filename]};
  };
  localWin.eval(js);
  await new Promise(resolve => setTimeout(resolve, 180));
  const localDoc = localWin.document;
  assert.match(localDoc.querySelector('#vision-status').textContent, /JEV готовий/);
  assert.match(localDoc.querySelector('#connection-pill').textContent, /JEV готовий/, 'local header reflects Ollama, not archive feeds');
  localDoc.querySelector('#chart-timeframe').value = '1m';
  const localInput = localDoc.querySelector('#chart-photo');
  Object.defineProperty(localInput, 'files', { configurable: true, value: [
    { name: 'paste.png', type: 'image/png', size: 1000 }
  ] });
  localInput.dispatchEvent(new localWin.Event('change', {bubbles: true}));
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(imageCalls, 1, 'local image should be analyzed once');
  assert.ok(healthChecks >= 2, 'local health checked at startup and before inference');
  assert.match(localDoc.querySelector('#photo-analysis .jev-image-result').textContent, /BUY/);
  assert.match(localDoc.querySelector('#photo-analysis .jev-image-result').textContent, /1 хвилина/);
  assert.match(localDoc.querySelector('#photo-analysis .jev-image-result').textContent, /неперевірена гіпотеза/);
  assert.doesNotMatch(localDoc.querySelector('#photo-analysis').textContent, /червоних ділянок/);

  // Paste from the Windows Snipping Tool must also trigger analysis.
  const paste = new localWin.Event('paste', {bubbles: true, cancelable: true});
  Object.defineProperty(paste, 'clipboardData', {value: {
    items: [{kind: 'file', type: 'image/png', getAsFile: () => ({name: 'clip.png', type: 'image/png', size: 1000})}],
    files: []
  }});
  localDoc.dispatchEvent(paste);
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(imageCalls, 2, 'Ctrl+V screenshot should be analyzed');
  assert.match(localDoc.querySelector('#photo-analysis .jev-image-result').textContent, /ПРОПУСТИТИ/);
  assert.match(localDoc.querySelector('#photo-analysis .jev-image-result').textContent, /не рекомендовано/);
  assert.equal(paste.defaultPrevented, true);
  localWin.close();
  win.close();
  console.log('Crypto Myshka: screens, saved history, full-res photo, Ctrl+V, local JEV health, demo BUY/SELL/SKIP expiry and cloud fallback passed');
})().catch(error => { console.error(error); process.exit(1); });
