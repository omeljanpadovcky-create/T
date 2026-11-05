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
- GitHub Actions (`.github/workflows/myshka-job-radar.yml`) — пошук о 07:00 та 14:00 UTC; у зимовий час це 09:00 та 16:00 у Києві, у літній — 10:00 та 17:00.
- Той самий workflow опитує Telegram кожні 5 хвилин для обробки кнопок та редагування Cover Letter. Стан вакансій, offset і редагування зберігаються у `jobs/*.json` комітами GitHub Actions.
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

Після додавання змінних запусти workflow `MYSHKA JOB RADAR` вручну через GitHub Actions або дочекайся розкладу. Перевір, що в репозиторії → Settings → Actions → General дозволені workflow та запис у репозиторій. Переконайся, що додані GitHub Secrets `TELEGRAM_BOT_TOKEN` і `TELEGRAM_CHAT_ID`.

## Безпека та межі
Система готує вакансії та матеріали для ручної перевірки. Вона не відправляє заявки без явного підтвердження, не обходить CAPTCHA та не імітує авторизацію. Доступність джерел вакансій може змінюватися.

## GitHub Pages
Settings → Pages → Deploy from a branch → `main` → `/ (root)`.
