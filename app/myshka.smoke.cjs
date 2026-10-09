/* Run with node app/myshka.smoke.cjs (requires jsdom). No external API requests. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { JSDOM } = require('jsdom');

(async () => {
  const root = path.resolve(__dirname, '..');
  const html = fs.readFileSync(path.join(root, 'myshka-app.html'), 'utf8');
  const js = fs.readFileSync(path.join(root, 'app/myshka.js'), 'utf8');
  const archiveScript=fs.readFileSync(path.join(root, 'app/myshka-archive.js'), 'utf8');
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
  const library = {
    updated_at: new Date().toISOString(), status: 'partial_or_growing', progress: {},
    channels: [{id:'backstage',name:'Закулисье Трейдера'},{id:'alexey',name:'Алексей Борщев'}],
    videos:[
      {id:'Z4HMrRpKcV4',channel_id:'backstage',channel_name:'Закулисье Трейдера',
       title:'BTC trading RSI tutorial', kind:'videos', upload_date:'20261009',
       caption_status:'available',content_status:'captions_scanned',
       jev:{status:'model_summary',summary:'Пояснює роботу RSI.',strategy:'RSI',risk:'Торгові результати не перевірено.'},
       gemini:{status:'gemini_video_summary',summary:'Gemini бачить графік і чує автора',
         strategy:'RSI та свічки',risk:'Котирування не підтверджено',
         pairs:['BTC/USDT'],indicators:['RSI'],timeframes:['M1'],
         moments:[{timestamp:'00:20',observation:'Показано свічковий графік'}]},

       analysis:{mentioned_instruments:['BTC/USDT'],mentioned_indicators:['RSI']}},
      {id:'bpQLYZM2FfE',channel_id:'alexey',channel_name:'Алексей Борщев',
       title:'Forex short lesson',kind:'videos',upload_date:null,
       caption_status:'unavailable',content_status:'title_description_only',
       jev:{status:'not_analyzed'},analysis:{}}
    ]
  };
  const data = { 'youtube_live.json': live, 'pair_reports.json': reports, 'youtube_analysts.json': analysts,
    'youtube_archive.json': library };
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
  win.eval(archiveScript);
  win.eval(js);
  await new Promise(resolve => setTimeout(resolve, 180));
  const doc = win.document;
  const click = selector => {
    const el = doc.querySelector(selector);
    assert.ok(el, 'Missing control: ' + selector);
    el.click();
    return el;
  };
  assert.equal(doc.querySelectorAll('.bottom-nav button').length, 5, 'archive is fifth mobile screen');
  assert.equal(doc.querySelector('#screen-live'), null, 'LIVE Monitor screen must be removed');
  assert.equal(doc.querySelector('[data-go="live"]'), null, 'LIVE Monitor links must be removed');
  assert.doesNotMatch(doc.querySelector('#screen-home').textContent, /НИКОЛАС|LIVE Monitor/);
  click('.bottom-nav [data-go="archive"]');
  await new Promise(resolve => setTimeout(resolve, 160));
  assert.equal(doc.querySelector('#screen-archive').hidden, false, 'video archive tab visible');
  assert.match(doc.querySelector('#archive-list').textContent, /BTC trading RSI tutorial/);
  assert.match(doc.querySelector('#archive-list').textContent, /JEV: конспект субтитрів/);
  assert.match(doc.querySelector('#archive-list').textContent, /Gemini · аналіз відео та звуку/);
  assert.match(doc.querySelector('#archive-list').textContent, /00:20/);
  assert.equal(doc.querySelector('#archive-count').textContent, '2');
  assert.equal(doc.querySelector('#archive-gemini-count').textContent, '1');
  assert.equal(doc.querySelector('#archive-caption-count').textContent, '1');
  assert.equal(doc.querySelector('#archive-jev-count').textContent, '1');
  const evidence=doc.querySelector('#archive-evidence');
  evidence.value='gemini';evidence.dispatchEvent(new win.Event('change',{bubbles:true}));
  assert.equal(doc.querySelectorAll('#archive-list .archive-card').length,1);
  evidence.value='';evidence.dispatchEvent(new win.Event('change',{bubbles:true}));
  const archiveInput=doc.querySelector('#archive-query');
  archiveInput.value='RSI';
  archiveInput.dispatchEvent(new win.Event('input',{bubbles:true}));
  assert.equal(doc.querySelectorAll('#archive-list .archive-card').length,1);
  archiveInput.value='';
  archiveInput.dispatchEvent(new win.Event('input',{bubbles:true}));
  const authorFilter=doc.querySelector('#archive-channel');
  authorFilter.value='alexey';
  authorFilter.dispatchEvent(new win.Event('change',{bubbles:true}));
  assert.match(doc.querySelector('#archive-list').textContent,/Forex short lesson/);
  assert.doesNotMatch(doc.querySelector('#archive-list').textContent,/BTC trading RSI tutorial/);
  authorFilter.value='';
  authorFilter.dispatchEvent(new win.Event('change',{bubbles:true}));
  assert.equal(doc.querySelector('#stat-pairs').textContent, '1');
  assert.match(doc.querySelector('#connection-pill').textContent, /Підключи хмарний JEV/, 'cloud without a backend must not fake readiness');
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
  assert.match(doc.querySelector('#vision-status').textContent, /локальний JEV доступний лише|Локальний JEV доступний лише/);
  const modeOnPublic = doc.querySelector('#vision-mode-select');
  modeOnPublic.value = 'local';
  modeOnPublic.dispatchEvent(new win.Event('change', {bubbles: true}));
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.equal(doc.querySelector('#local-mode-warning').hidden, false, 'public GitHub Pages explains that Ollama cannot be used here');
  assert.match(doc.querySelector('#connection-pill').textContent, /Ollama: відкрий локальну Мишку/);
  modeOnPublic.value = 'auto';
  modeOnPublic.dispatchEvent(new win.Event('change', {bubbles: true}));
  await new Promise(resolve => setTimeout(resolve, 30));
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
  const hitButton = Array.from(localDoc.querySelectorAll('.expiry-outcome-row button'))
    .find(button => button.textContent.includes('влучив'));
  assert.ok(hitButton, 'manual demo outcome control is visible');
  hitButton.click();
  const outcomes = JSON.parse(localWin.localStorage.getItem('crypto-myshka-demo-expiry-v1'));
  assert.equal(outcomes.length, 1);
  assert.equal(outcomes[0].expiry, 60);
  assert.equal(outcomes[0].correct, true);
  assert.match(localDoc.querySelector('#expiry-journal-summary').textContent, /1 хв: 1\/1/);
  assert.equal(hitButton.disabled, true);
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
  // GitHub Pages with an explicitly configured Vercel backend uses remote
  // health and image inference; the access code never appears in GitHub source.
  const cloudDom = new JSDOM(html, {
    url: 'https://omeljanpadovcky-create.github.io/T/myshka-app.html#analysis',
    pretendToBeVisual: true, runScripts: 'outside-only'
  });
  const cloudWin = cloudDom.window;
  cloudWin.scrollTo = () => {};
  cloudWin.FileReader = win.FileReader;
  cloudWin.Image = win.Image;
  cloudWin.localStorage.setItem('crypto-myshka-app-v1', JSON.stringify({
    theme:'light', refresh:15, visionMode:'cloud', cloudFallback:false, saved:{},votes:{}
  }));
  cloudWin.localStorage.setItem('crypto-myshka-cloud-endpoint-v1', 'https://myshka-ai.vercel.app');
  cloudWin.sessionStorage.setItem('crypto-myshka-cloud-access-session-v1', 'abcdefghijklmnopqrstuvwxyz123456');
  let cloudHealth = 0, cloudImages = 0;
  cloudWin.fetch = async (url, opts = {}) => {
    if (String(url).includes('myshka-ai.vercel.app/api/chart-health')) {
      cloudHealth++;
      assert.equal(opts.headers['X-JEV-Access'], 'abcdefghijklmnopqrstuvwxyz123456');
      return {ok:true,json:async()=>({ready:true,cloud:true,model:'gemini-2.5-flash'})};
    }
    if (String(url).includes('myshka-ai.vercel.app/api/chart-analysis')) {
      cloudImages++;
      assert.equal(opts.headers['X-JEV-Access'], 'abcdefghijklmnopqrstuvwxyz123456');
      assert.equal(opts.headers['Content-Type'], 'application/json');
      assert.equal(JSON.parse(opts.body).chart_timeframe, '1m');
      return {ok:true,json:async()=>({
        direction:'ВНИЗ',action:'SELL',test_expiry_seconds:60,
        chart_timeframe:'1m',timeframe_source:'user',
        reason:'Видно кілька нижчих максимумів на графіку.'
      })};
    }
    const filename = String(url).split('/').pop().split('?')[0];
    if (!data[filename]) throw Error('Unexpected cloud resource: '+url);
    return {ok:true,json:async()=>data[filename]};
  };
  cloudWin.eval(js);
  await new Promise(resolve => setTimeout(resolve, 180));
  const cloudDoc = cloudWin.document;
  assert.match(cloudDoc.querySelector('#connection-pill').textContent, /JEV хмарний готовий/);
  assert.match(cloudDoc.querySelector('#vision-status').textContent, /хмарний Gemini/);
  cloudDoc.querySelector('#chart-timeframe').value = '1m';
  const cloudInput = cloudDoc.querySelector('#chart-photo');
  Object.defineProperty(cloudInput, 'files', {configurable:true,value:[
    {name:'cloud.png',type:'image/png',size:1000}
  ]});
  cloudInput.dispatchEvent(new cloudWin.Event('change',{bubbles:true}));
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.ok(cloudHealth >= 2);
  assert.equal(cloudImages,1);
  assert.match(cloudDoc.querySelector('#photo-analysis .jev-image-result').textContent,/SELL/);
  assert.match(cloudDoc.querySelector('#photo-analysis .jev-image-result').textContent,/хмарним AI/);
  cloudDoc.querySelector('#cloud-disconnect').click();
  await new Promise(resolve => setTimeout(resolve, 30));
  assert.match(cloudDoc.querySelector('#connection-pill').textContent,/Підключи хмарний JEV/);
  assert.equal(cloudWin.sessionStorage.getItem('crypto-myshka-cloud-access-session-v1'),null);

  // Dual-mode privacy regression: no cloud calls without explicit consent.
  const autoDom = new JSDOM(html, {
    url: 'http://127.0.0.1:18765/myshka-app.html#analysis',
    pretendToBeVisual: true, runScripts: 'outside-only'
  });
  const autoWin = autoDom.window;
  autoWin.scrollTo = () => {};
  autoWin.FileReader = win.FileReader;
  autoWin.Image = win.Image;
  autoWin.localStorage.setItem('crypto-myshka-app-v1', JSON.stringify({
    theme:'light',refresh:15,visionMode:'auto',cloudFallback:false,saved:{},votes:{}
  }));
  autoWin.localStorage.setItem('crypto-myshka-cloud-endpoint-v1', 'https://myshka-ai.vercel.app');
  autoWin.sessionStorage.setItem('crypto-myshka-cloud-access-session-v1', 'abcdefghijklmnopqrstuvwxyz123456');
  let offlineLocalHealth = 0, remoteHealth = 0, remoteImages = 0, localImages = 0;
  autoWin.fetch = async (url, opts = {}) => {
    const address = String(url);
    if (address.startsWith('https://myshka-ai.vercel.app/api/chart-health')) {
      remoteHealth++;
      assert.equal(opts.headers['X-JEV-Access'], 'abcdefghijklmnopqrstuvwxyz123456');
      return {ok:true,status:200,json:async()=>({
        ready:true,cloud:true,provider:'apinex',model:'gemini-3.8-flash',verified:false
      })};
    }
    if (address.startsWith('https://myshka-ai.vercel.app/api/chart-analysis')) {
      remoteImages++;
      assert.equal(JSON.parse(opts.body).image, 'aGVsbG8=');
      return {ok:true,status:200,json:async()=>({
        direction:'НЕВИЗНАЧЕНО',action:'SKIP',test_expiry_seconds:null,
        chart_timeframe:'unknown',timeframe_source:'unknown',reason:'Мало даних.',
        provider:'apinex'
      })};
    }
    if (address.includes('/api/chart-health')) {
      offlineLocalHealth++;
      return {ok:false,status:503,json:async()=>({ready:false,ollama:false,error:'Ollama offline'})};
    }
    if (address.includes('/api/chart-analysis')) {
      localImages++;
      throw Error('The offline local model must never receive image analysis');
    }
    const filename = address.split('/').pop().split('?')[0];
    if (!data[filename]) throw Error('Unexpected auto resource: '+address);
    return {ok:true,json:async()=>data[filename]};
  };
  autoWin.eval(js);
  await new Promise(resolve => setTimeout(resolve, 100));
  const autoDoc = autoWin.document;
  assert.equal(remoteHealth, 0, 'AUTO mode must not probe the cloud without permission');
  assert.equal(remoteImages, 0, 'AUTO mode must never send images without consent');
  assert.equal(autoDoc.querySelector('#vision-mode-quick').value, 'auto');
  const consent = autoDoc.querySelector('#vision-cloud-fallback');
  assert.equal(consent.checked, false, 'cloud fallback should default to OFF');
  consent.checked = true;
  consent.dispatchEvent(new autoWin.Event('change', {bubbles:true}));
  await new Promise(resolve => setTimeout(resolve, 80));
  assert.ok(offlineLocalHealth >= 2, 'prefer local health in AUTO');
  assert.ok(remoteHealth >= 1, 'cloud health checked only after consent');
  assert.match(autoDoc.querySelector('#vision-status').textContent, /APInex|хмарний/);
  const upload = (name) => {
    const input = autoDoc.querySelector('#chart-photo');
    Object.defineProperty(input, 'files', {configurable:true,value:[
      {name,type:'image/png',size:1000}
    ]});
    input.dispatchEvent(new autoWin.Event('change',{bubbles:true}));
  };
  upload('fallback.png');
  await new Promise(resolve => setTimeout(resolve, 100));
  assert.equal(remoteImages, 1, 'explicit cloud fallback analyzes the screenshot');
  assert.equal(localImages, 0);
  assert.match(autoDoc.querySelector('#photo-analysis .jev-image-result').textContent,/хмарним AI|резервний режим/);
  consent.checked = false;
  consent.dispatchEvent(new autoWin.Event('change', {bubbles:true}));
  await new Promise(resolve => setTimeout(resolve, 40));
  upload('no-consent.png');
  await new Promise(resolve => setTimeout(resolve, 60));
  assert.equal(remoteImages, 1, 'disabling consent immediately blocks cloud screenshot fallback');
  const quick = autoDoc.querySelector('#vision-mode-quick');
  quick.value = 'cloud';
  quick.dispatchEvent(new autoWin.Event('change',{bubbles:true}));
  await new Promise(resolve => setTimeout(resolve, 40));
  assert.equal(autoDoc.querySelector('#vision-mode-select').value,'cloud');
  upload('explicit-cloud.png');
  await new Promise(resolve => setTimeout(resolve, 70));
  assert.equal(remoteImages, 2, 'manual CLOUD selection permits cloud-only analysis');
  quick.value = 'local';
  quick.dispatchEvent(new autoWin.Event('change',{bubbles:true}));
  await new Promise(resolve => setTimeout(resolve, 40));
  upload('local-only.png');
  await new Promise(resolve => setTimeout(resolve, 70));
  assert.equal(remoteImages, 2, 'LOCAL mode cannot upload a screenshot to APInex');
  autoWin.close();
  cloudWin.close();
  localWin.close();
  win.close();
  console.log('Crypto Myshka: local Ollama, optional authenticated cloud JEV, no-backend fallback, demo expiry, screenshots, Ctrl+V and journal passed');
})().catch(error => { console.error(error); process.exit(1); });
