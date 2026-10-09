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
  assert.equal(doc.querySelectorAll('.bottom-nav button').length, 5, 'all five screens must have mobile navigation');
  assert.equal(doc.querySelector('#stat-channels').textContent, '2');
  assert.equal(doc.querySelector('#stat-live').textContent, '0', 'offline cannot be presented as LIVE');
  assert.equal(doc.querySelector('#stat-pairs').textContent, '1');
  click('.bottom-nav [data-go="live"]');
  assert.equal(doc.querySelector('#screen-live').hidden, false);
  assert.match(doc.querySelector('#live-list').textContent, /НИКОЛАС/);
  assert.match(doc.querySelector('#live-list').textContent, /LIVE не підтверджено/);
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
  assert.match(doc.querySelector('#analysis-list').textContent, /Очікуємо перший LIVE-аналіз/);
  click('#demo-button');
  assert.match(doc.querySelector('#analysis-list').textContent, /ДЕМОНСТРАЦІЯ ІНТЕРФЕЙСУ/);
  assert.match(doc.querySelector('#analysis-list').textContent, /AUD\/CNY OTC/);
  assert.equal(doc.querySelector('#analysis-list .report-actions'), null, 'demo must not offer to save or rate a fake report');
  click('#demo-button');
  assert.match(doc.querySelector('#analysis-list').textContent, /Очікуємо перший LIVE-аналіз/);
  win.close();
  console.log('✅ Crypto Myshka app: 5 screens, LIVE, JEV detail, saved history, settings & empty state passed');
})().catch(error => { console.error(error); process.exit(1); });
