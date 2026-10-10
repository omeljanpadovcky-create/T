/* Market bridge: verified public OHLCV -> deterministic summary or explicit opt-in cloud JEV.
 * No synthetic trades, no account permissions and no credentials in source code.
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const status = $('jev-market-status');
  const output = $('jev-market-output');
  const ask = $('jev-market-ask');
  const question = $('jev-market-question');
  if (!status || !output || !ask || !question) return;
  let busy = false;
  let lastSnapshot = null;
  const number = n => Number.isFinite(n) ? n.toLocaleString('uk-UA',{maximumFractionDigits:5}) : '—';
  const percentage = n => Number.isFinite(n) ? (n > 0 ? '+' : '') + n.toFixed(2) + '%' : '—';
  const setText = (element, text) => { element.textContent = text; };
  function explain(m) {
    if (!m) return 'Потрібно спершу отримати підтверджені свічки Bybit. Натисни «Аналізувати Bybit».';
    const r = m.indicators;
    const direction = r.ema9 > r.ema21 ? 'EMA 9 вище EMA 21 — локальний висхідний нахил.' :
      r.ema9 < r.ema21 ? 'EMA 9 нижче EMA 21 — локальний спадний нахил.' : 'Лінії EMA збігаються.';
    const rsi = r.rsi14 >= 70 ? 'RSI у високій зоні, що НЕ гарантує розвороту.' :
      r.rsi14 <= 30 ? 'RSI у низькій зоні, що НЕ гарантує відскоку.' :
      'RSI у проміжному діапазоні, без однозначного висновку.';
    const vol = Number.isFinite(r.volumeRatio) ? (r.volumeRatio >= 1.4 ?
      'Обсяг останньої завершеної свічки перевищує середній 20 свічок.' :
      r.volumeRatio < 0.75 ? 'Обсяг нижчий за середній — підтвердження руху слабше.' :
      'Обсяг близький до середнього.') : 'Обсяг не вдалося порівняти.';
    return [
      'МАТЕМАТИЧНИЙ ОГЛЯД · НЕ AI',
      m.symbol + ' · ' + m.intervalMinutes + ' хв · ' + m.completedCandles + ' завершених свічок',
      'Остання свічка закрилася: ' + new Date(m.lastClosedAt).toLocaleString('uk-UA'),
      'Ціна закриття: ' + number(r.lastClose) + ' USDT. Рух 5 свічок: ' + percentage(r.change5Pct) + '.',
      direction, 'RSI 14: ' + number(r.rsi14) + '. ' + rsi, vol,
      'Мінімум/максимум 20 свічок: ' + number(r.support) + ' / ' + number(r.resistance) + ' USDT.',
      'Висновок: ' + r.regime + '. Це лише опис минулих свічок; надійного прогнозу напрямку немає.',
      'Комісії, funding, спред, slippage та підтверджені позиції трейдерів не враховані. Реальні ордери не відкриваються.'
    ].join('\n\n');
  }
  function render(snapshot) {
    lastSnapshot = snapshot;
    setText(output,explain(snapshot));
    status.textContent = snapshot
      ? '✅ Реальні OHLCV Bybit отримано. Показано математичний огляд; для відповіді AI натисни кнопку нижче.'
      : '⚪ Немає підтверджених свічок для JEV. Огляд не створено.';
    ask.disabled = busy || !snapshot;
  }
  window.addEventListener('crypto-myshka-market', e => render(e.detail || null));
  render(window.cryptoMyshkaPublicAnalysis?.getLastReport?.() || null);
  function credentials() {
    let endpoint = '', access = '';
    try { endpoint = localStorage.getItem('crypto-myshka-cloud-endpoint-v1') || ''; } catch {}
    try { access = sessionStorage.getItem('crypto-myshka-cloud-access-session-v1') || ''; } catch {}
    if (!endpoint) endpoint = 'https://t-zeta-ashy.vercel.app';
    try {
      const u = new URL(endpoint);
      if (u.protocol !== 'https:' || u.pathname !== '/' || u.search || u.hash || u.username || u.password) return null;
      return { endpoint:u.origin, access };
    } catch { return null; }
  }
  ask.addEventListener('click', async () => {
    const snapshot = lastSnapshot;
    if (busy || !snapshot) return;
    const cfg = credentials();
    if (!cfg || cfg.access.length < 24) {
      status.textContent = '🔑 Для окремого AI-аналізу відкрий «Налаштування» та підключи хмарний JEV. Математичний аналіз працює без ключа.';
      return;
    }
    busy = true;
    ask.disabled = true;
    const view = explain(snapshot);
    status.textContent = '⏳ Передаємо вибрані фактичні показники Bybit до JEV. Жодних ордерів.';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(),29000);
    try {
      const prompt = [
        'PUBLIC_BYBIT_OHLCV: Оціни ці підтверджені завершені свічки як дослідник, а не як торговий радник.',
        'Факти з Bybit V5, дата закриття у UTC, не вигадуй інші ціни або статистику трейдерів.',
        'Скажи: (1) що видно, (2) висхідний/спадний/боковий сценарії, (3) ризики та що перевірити.',
        'Без імперативів купити/продати, гарантій, псевдо-точності чи прямого копіювання сигналів.',
        'DATA: ' + JSON.stringify(snapshot),
        'Додаткове запитання: ' + question.value.trim().slice(0,240)
      ].join('\n');
      const response = await fetch(cfg.endpoint + '/api/jev-chat', {
        method:'POST', headers:{'Content-Type':'application/json','X-JEV-Access':cfg.access},
        body:JSON.stringify({message:prompt}), signal:controller.signal, cache:'no-store'
      });
      let data;
      try { data = await response.json(); } catch { data = {}; }
      if (!response.ok || typeof data.reply !== 'string' || !data.reply.trim())
        throw new Error(data.error || 'JEV недоступний (HTTP ' + response.status + ')');
      if (snapshot !== lastSnapshot) {
        status.textContent = 'ℹ️ Поки AI відповідав, ринок оновився. Стару відповідь не показуємо: запусти JEV ще раз.';
        return;
      }
      setText(output,'JEV · СПРАВЖНЯ AI-ВІДПОВІДЬ\n' + data.reply.trim() +
        '\n\nПровайдер: ' + String(data.provider||'—') + ' · Модель: ' + String(data.model||'—') +
        '\nДжерело котирувань: Bybit V5 · ' + new Date(snapshot.lastClosedAt).toLocaleString('uk-UA') +
        '\nНе є торговим сигналом. Автоматичні угоди вимкнені.');
      status.textContent = '✅ AI дав відповідь на дані завершених свічок. Не плутай її з незалежною перевіркою ціни.';
    } catch(err) {
      setText(output,view);
      const why = err?.name === 'AbortError' ? 'Тайм-аут JEV (29 секунд).' : String(err?.message || 'AI недоступний').slice(0,260);
      status.textContent = '⚠️ AI не підтверджено: ' + why + ' Математичний огляд збережено вище.';
    } finally {
      clearTimeout(timer); busy = false; ask.disabled = !lastSnapshot;
    }
  });
})();
