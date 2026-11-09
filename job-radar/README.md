# ТРЕЙДМИШКА — Job Radar

The vacancy scan runs through GitHub Actions every 15 minutes. Telegram buttons and chat messages are received by a Vercel webhook and dispatched to a dedicated GitHub Actions workflow for processing. The webhook acknowledges callback taps immediately; the application action is then processed asynchronously.

## Search profile
- Minimum score: 80/100.
- Remote work: Ukraine, Europe and worldwide where the listing clearly permits it.
- Roles: 3D / Blender / modeling, Game Art / game assets, character / environment / prop art, concept art, illustration, book covers, Photobashing and Matte Painting.
- English level and seniority are not automatic rejection filters.
- Country-specific locations and explicit country-only requirements are filtered out unless Ukraine or a broader eligible region is explicitly allowed.
- Some public sources can return 403 or change their markup. The radar records failures and continues with sources that respond.

## Telegram workflow
Each vacancy card contains the original listing link and actions to prepare an application, generate a cover letter, save for later, skip, or view status. Selecting a vacancy generates an editable application package. The user reviews and approves the package, then submits manually on the employer's website. The bot never submits an application automatically.

## Vercel environment variables
Configure these in the `myshka-job-radar` Vercel project for Production:
- `TELEGRAM_BOT_TOKEN` — existing Telegram bot token.
- `TELEGRAM_CHAT_ID` — existing private chat ID.
- `TELEGRAM_WEBHOOK_SECRET` — random secret (1–256 characters; only A–Z, a–z, 0–9, underscore and hyphen).
- `MYSHKA_GITHUB_DISPATCH_TOKEN` — GitHub fine-grained token for repository `omeljanpadovcky-create/T`, with **Contents: Read and write** permission. Do not expose this token in the repository or browser.

After deployment, register the webhook by sending a POST request to `/api/telegram-webhook-setup` with header `Authorization: Bearer <CRON_SECRET>`. The endpoint preserves pending Telegram updates.

## Deployment
Vercel serves the webhook endpoints from this directory. GitHub Actions remains responsible for the vacancy scan and for executing callback actions. Telegram polling via `getUpdates` is no longer part of the scheduled scan.
