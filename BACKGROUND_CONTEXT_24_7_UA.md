# MYSHKA / ASTRA — Background Context 24/7

Цей патч додає окремий фоновий збирач контексту, який працює незалежно від торгового `auto_scan`.

## Що збирається

Щохвилини для поточного TOP-15 universe:

- last / mark / index price;
- bid/ask spread;
- funding rate;
- open interest;
- 24h turnover і volume;
- 5/15/30-хвилинна зміна ціни;
- 5/15/30-хвилинна зміна open interest.

Раз на ~5 хвилин:

- Bybit long/short account ratio;
- RSS headlines із налаштованих крипто-джерел.

Також є `POST /context/ingest`, куди n8n може фоном надсилати зовнішні події з X, новин, APInex або інших джерел.

## Зберігання

Контекст пишеться в `/data/myshka_context.sqlite3` і зберігається за замовчуванням 48 годин. Для кожного сигналу ASTRA додає snapshot останніх 30 хвилин.

## SHADOW mode

Поки що контекст **не має права** сам створити `ENTER`, `DROP` або обійти Guard. Він лише записується разом із рішенням та показується в Telegram як `CTX SHADOW`.

Це зроблено навмисно: спочатку накопичуємо достатньо STRICT-угод і дивимося, чи контекст реально розділяє хороші/погані входи. Після цього можна перетворити перевірені ознаки на `CONTEXT PASS/WARN/FAIL`.

## Встановлення

У PowerShell:

```powershell
cd $HOME\Downloads
Invoke-WebRequest -Uri "https://raw.githubusercontent.com/omeljanpadovcky-create/T/main/INSTALL_BACKGROUND_CONTEXT_24_7.ps1" -OutFile "INSTALL_BACKGROUND_CONTEXT_24_7.ps1"
powershell -ExecutionPolicy Bypass -File .\INSTALL_BACKGROUND_CONTEXT_24_7.ps1
```

Після `READY` перевір:

```powershell
Invoke-RestMethod http://127.0.0.1:8088/context/status
```

Через Telegram у кожному scan з'явиться рядок на кшталт:

```text
CTX SHADOW: n=18 · age 12s · Δ5m -0.120% · Δ15m -0.340% · OI15 +1.800% · fund +0.0100% · L/S +0.82 · ext 2
```

## External ingest для n8n

`POST http://host.docker.internal:8088/context/ingest`

JSON приклад:

```json
{
  "source": "n8n-x",
  "kind": "social",
  "pair": "BTC/USDT:USDT",
  "text": "short summary from X",
  "sentiment": "bearish",
  "score": -0.6
}
```

Якщо подія загальна для всього ринку — використовуй `"pair": "*"`.
