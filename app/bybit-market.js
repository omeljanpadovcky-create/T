/* Read-only official Bybit V5 public ticker context. No keys, trades or copying. */
(() => {
  'use strict';
  const status = document.getElementById('bybit-market-status');
  const target = document.getElementById('bybit-market-data');
  const refresh = document.getElementById('bybit-market-refresh');
  if (!status || !target) return;
  const pairs = ['BTCUSDT','ETHUSDT','SOLUSDT'];
  let pending = false;
  const format = n => Number.isFinite(n) ? n.toLocaleString('uk-UA',{maximumFractionDigits:6}) : '—';
  async function update() {
    if (pending) return;
    pending = true;
    if (refresh) refresh.disabled = true;
    status.textContent = 'Завантажуємо публічні котирування Bybit…';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 10000);
    try {
      const response = await fetch('https://api.bybit.com/v5/market/tickers?category=linear', {signal:controller.signal,cache:'no-store'});
      if (!response.ok) throw Error('HTTP '+response.status);
      const data = await response.json();
      if (data.retCode !== 0 || !Array.isArray(data.result?.list)) throw Error('Некоректна відповідь API');
      const bySymbol = new Map(data.result.list.map(x => [x.symbol,x]));
      const tbody = document.createElement('tbody');
      for (const symbol of pairs) {
        const ticker = bySymbol.get(symbol);
        if (!ticker) throw Error('Немає даних '+symbol);
        const price = Number(ticker.lastPrice);
        const change = Number(ticker.price24hPcnt)*100;
        const tr = document.createElement('tr');
        for (const value of [symbol,format(price)+' USDT',format(change)+'%']) {
          const td = document.createElement('td');
          td.textContent = value;
          td.style.padding = '7px 10px 7px 0';
          tr.appendChild(td);
        }
        tbody.appendChild(tr);
      }
      const table = document.createElement('table');
      table.style.width = '100%';
      table.style.textAlign = 'left';
      table.style.fontSize = '13px';
      const head = document.createElement('thead');
      const row = document.createElement('tr');
      for (const label of ['Пара','Остання ціна','Зміна 24 год']) {
        const th=document.createElement('th'); th.textContent=label;row.appendChild(th);
      }
      head.appendChild(row);table.appendChild(head);table.appendChild(tbody);
      target.replaceChildren(table);
      status.textContent = 'Оновлено: '+new Date().toLocaleString('uk-UA')+' · публічні дані, не угоди трейдерів';
    } catch(e) {
      status.textContent = 'Немає доступу до публічних котирувань Bybit ('+(e.name==='AbortError'?'тайм-аут':'мережа/API')+').';
    } finally {
      clearTimeout(timer);
      pending=false;
      if (refresh) refresh.disabled=false;
    }
  }
  if (refresh) refresh.addEventListener('click',update);
  update();
  setInterval(() => { if (!document.hidden) update(); },60000);
})();
