# ТрейдМишка — Personal Job Radar

Основний проєкт репозиторію — персональна система пошуку віддаленої оплачуваної роботи у 3D, Blender, Game Art та ілюстрації.

## Структура
- `index.html` — головна сторінка GitHub Pages.
- `job-radar/` — вебпанель та серверні API для пошуку вакансій і Telegram.
- `job-radar/api/check.js` — збір, оцінка, фільтрація та надсилання вакансій.
- `job-radar/api/health.js` — технічний статус конфігурації.
- `job-radar/api/telegram-setup.js` — Telegram setup.
- `job-radar/vercel.json` — розклад серверного запуску.

## Профіль пошуку
Remote з України; 3D/Blender/Game Art та ілюстрація; trainee/junior/middle, freelance, contract, part-time та full-time. Враховувати реальні вимоги вакансії. До 10 релевантних сповіщень на день — не заповнювати ліміт випадковими оголошеннями.

## Архітектура
- GitHub Pages — статична вебпанель.
- GitHub Actions — щоденний пошук о 07:00 UTC.
- Vercel (Root Directory: `job-radar`) — додаткові API та діагностика; cron вимкнений, щоб не було подвійних сповіщень.
- Telegram Bot API — сповіщення.
- Vercel Environment Variables — секрети.
- Upstash Redis — рекомендоване постійне сховище дедуплікації.

## Налаштування Vercel
Встановити Root Directory = `job-radar`, Framework Preset = Other. Додати змінні:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `CRON_SECRET`
- `UPSTASH_REDIS_REST_URL` та `UPSTASH_REDIS_REST_TOKEN` (рекомендовано)

Після додавання змінних зробити Redeploy. Перевірити `/api/health`, потім вручну запустити `/api/check` із заголовком `Authorization: Bearer <CRON_SECRET>`.

## Безпека та межі
Система готує вакансії та матеріали для ручної перевірки. Вона не відправляє заявки без явного підтвердження, не обходить CAPTCHA та не імітує авторизацію. Доступність джерел вакансій може змінюватися.

## GitHub Pages
Settings → Pages → Deploy from a branch → `main` → `/ (root)`.
