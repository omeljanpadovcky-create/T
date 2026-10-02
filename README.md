# MYSHKA P2P RADAR

Цей репозиторій тепер сфокусований на P2P-радарі: скан → розрахунок спреду → risk score → Telegram alert. Гроші та ордери він сам не відправляє.

## Запуск

1. Відкрий `p2p_radar/.env` і встав Telegram:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`
2. Двічі натисни `START_P2P_RADAR.bat`.
3. Якщо хочеш, щоб радар стартував сам після входу у Windows — один раз запусти `INSTALL_P2P_AUTOSTART.bat`.

Якщо `p2p_radar/.env` ще немає, перший запуск створить його з `.env.example`. Старий кореневий `.env` теж читається.

## Що приходить у Telegram

Коли є маршрут, що проходить фільтри:
- де купити USDT;
- де продати USDT;
- BUY / SELL ціни;
- gross spread;
- estimated net % і приблизний результат у UAH;
- risk score;
- кнопки BUY / SELL;
- кнопка **«Я перевірив маршрут»**;
- кнопка **«Цикл завершено»**;
- pause / status.

Після **5 підтверджених перевірок маршруту за день** MYSHKA показує warning. Це внутрішній лічильник безпеки, а не банківський ліміт.

## Telegram-команди

- `/p2p_status`
- `/p2p_pause`
- `/p2p_resume`
- `/p2p_done`

## Bybit

Binance працює через read-only P2P feed. Bybit P2P API підключається, якщо у `.env` є `BYBIT_API_KEY` і `BYBIT_API_SECRET` та акаунт має потрібний P2P API access. Якщо Bybit недоступний, радар все одно може рахувати внутрішні Binance P2P маршрути.

## Сторінка

GitHub Pages dashboard:
https://omeljanpadovcky-create.github.io/T/

На сторінці BUY / SELL посилання теж мають денний лічильник: на 5-те відкриття з'являється warning.

Деталі: `p2p_radar/README.md`.


## Список бірж

MYSHKA більше не намагається "шукати біржі по інтернету". Вона проходить тільки явний список у `p2p_radar/exchanges.json`.

Поточний список:
- Binance
- Bybit
- OKX

Повний цикл запускається кожні **15 секунд**. Для кожної підключеної біржі MYSHKA бере BUY і SELL P2P-пропозиції, переводить їх у єдиний формат, перебирає комбінації, віднімає модель витрат/буфер і ранжує маршрути за net spread та risk score.

Щоб додати нову біржу, спочатку додається її `id` у `exchanges.json`, потім окремий adapter для її P2P market-data. Якщо adapter ще не підключений, біржа показується як OFF замість вигаданих котирувань.
