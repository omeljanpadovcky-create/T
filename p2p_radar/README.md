# MYSHKA P2P RADAR

One job only: **scan P2P markets, calculate a realistic cross-exchange spread, score risk, alert Telegram, and keep a detailed repository report.** It never opens, pays, releases, or closes orders.

## V1 providers

- **Binance**: read-only P2P website feed. It is isolated and gets an extra risk penalty because it is not a documented public P2P market-data API and can change.
- **Bybit**: official authenticated P2P API `/v5/p2p/item/online`. Bybit requires General Advertiser status or higher for P2P API access.
- The scanner keeps providers separate, so another exchange can be added without rewriting the risk/Telegram/report logic.

## Calculation

For every usable `buy exchange -> sell exchange` route the radar checks:
- the configured UAH amount fits both ad limits;
- merchant completion/orders when the feed exposes them;
- gross spread;
- transfer-fee drag;
- safety buffer;
- net UAH profit and net %;
- a separate prefunded scenario;
- risk score 0-100.

Verdicts:
- `ALERT`: net threshold passes and risk is acceptable;
- `PREFUNDED_ONLY`: only attractive if balances already sit on both exchanges;
- `DROP`: edge disappears after costs or risk is too high.

## Windows

Double-click **START_P2P_RADAR.bat**.

The first run creates `p2p_radar/.env`. The scanner also reads an existing root `.env`, so old Telegram/Bybit variables can be reused.

Telegram variable aliases:
- `TELEGRAM_BOT_TOKEN` or `TG_BOT_TOKEN`
- `TELEGRAM_CHAT_ID` or `TG_CHAT_ID`

## Repository output

- `p2p_radar/latest.json` - latest full snapshot for the dashboard;
- `p2p_radar/history.csv` - top route from every scan;
- `p2p_radar/reports/YYYY-MM-DD.md` - detailed periodic and alert reports.

With `P2P_GIT_PUSH=1`, the local clone commits/pushes reports automatically when a report is written. Git authentication must already work on the PC.

## Important

This is deliberately **not** an execution bot. Prices and P2P ads can disappear between scan and payment, so every Telegram alert is a candidate that still needs a live check.
