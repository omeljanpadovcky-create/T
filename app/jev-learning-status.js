/* Read-only transparency panel for scheduled cloud research. Not live trading advice. */
(() => {
  'use strict';
  const area = document.getElementById('jev-learning-status');
  if (!area) return;
  const uri = './crypto_myshka/data/market_learning_5m.json';
  const label = (iso) => {
    const timestamp = Date.parse(iso || '');
    return Number.isFinite(timestamp) ? new Date(timestamp).toLocaleString('uk-UA') : 'ще не підтверджено';
  };
  const fmt = (x) => Number.isFinite(Number(x)) ? Number(x).toLocaleString('uk-UA') : '—';
  function line(text) {
    const p = document.createElement('p');
    p.style.cssText = 'margin:5px 0;font-size:13px;line-height:1.6';
    p.textContent = text;
    return p;
  }
  async function update() {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 12000);
      let response;
      try { response = await fetch(uri + '?t=' + Date.now(), {cache:'no-store',signal:controller.signal}); }
      finally { clearTimeout(timer); }
      if (!response.ok) throw new Error('статистика ще не опублікована');
      const data = await response.json();
      if (data.version !== 1 || data.interval_minutes !== 5 || !data.symbols || data.orders_enabled !== false)
        throw new Error('формат статистики недоступний');
      const updated = Date.parse(data.updated_at || '');
      const stale = !Number.isFinite(updated) || Date.now() - updated > 30 * 60 * 1000;
      const title = document.createElement('strong');
      title.textContent = '☁️ JEV · Хмарний журнал ринку (5 хв)';
      const status = line('Джерело: ' + String(data.market || 'не підтверджене').slice(0, 100) + '. Останній підтверджений цикл: ' + label(data.updated_at) +
        (stale ? ' · автоматичні запуски не підтверджені вчасно; дані застарілі, гіпотези НЕ використовуй. Відкрий GitHub Actions для діагностики' :
          ' · хмарний процес не є безперервним потоком'));
      const fragment = document.createDocumentFragment();
      fragment.append(title,status);
      for (const symbol of ['BTCUSDT','ETHUSDT','SOLUSDT']) {
        const row = data.symbols[symbol];
        if (!row) continue;
        const held = row.backtest?.holdout || {};
        const fw = row.forward_observed || {};
        const verdict = stale ? 'СТОП (застаріло)' :
          row.latest_research_signal === 'UP' ? 'ВГОРУ (гіпотеза)' :
          row.latest_research_signal === 'DOWN' ? 'ВНИЗ (гіпотеза)' : 'СТОП';
        fragment.append(line(symbol + ' · ' + verdict +
          ' · історія: ' + fmt(row.backtest?.candles) + ' свічок' +
          ' · окрема історична перевірка: ' + fmt(held.observations) + ' випадків' +
          ' · майбутні результати: ' + fmt(fw.observations) + ' перевірених'));
      }
      if (stale) {
        const link=document.createElement('a');
        link.href='https://github.com/omeljanpadovcky-create/T/actions/workflows/jev-market-learning.yml';
        link.target='_blank';link.rel='noopener noreferrer';
        link.textContent='⚠️ Перевірити хмарні запуски GitHub Actions ↗';
        link.style.cssText='font-size:13px;display:inline-block;margin:8px 0;text-decoration:underline';
        fragment.append(link);
      }
      fragment.append(line('Минуле не доводить точності майбутнього. Віртуальні оцінки враховують припущені витрати, але не є результатами Bybit Demo Trading. Ордери вимкнені.'));
      area.replaceChildren(fragment);
    } catch (e) {
      area.replaceChildren(
        Object.assign(document.createElement('strong'),{textContent:'☁️ JEV · Хмарний журнал ринку'}),
        line('Ще немає підтвердженої опублікованої статистики. Перевір статус запусків GitHub Actions; результати не вигадуємо.')
      );
    }
  }
  update();
  setInterval(() => { if (!document.hidden) update(); }, 5 * 60 * 1000);
})();