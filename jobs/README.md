# ТРЕЙДМИШКА — Job Radar

Telegram job assistant for paid remote opportunities matching the user's creative profile.

## What it does
- Searches daily via GitHub Actions at 07:00 UTC.
- Sources: Arbeitnow, RemoteOK, Remotive (3D, Blender, Game Artist, Illustration, Concept Artist queries), and Himalayas.
- Targets 3D Artist, Blender Artist, 3D Modeler, Character Artist, Game Artist, Environment / Prop Artist, Illustrator, Concept Artist, Book Cover Artist and Cover Illustrator.
- Filters unpaid/volunteer work, clearly restricted US/Canada/Australia-only roles, and explicit English B2+ requirements.
- Sends up to 10 new matches to Telegram, ranked by fit.
- Adds Telegram inline buttons: Open vacancy, Confirm, Skip, Draft cover letter, Mark as applied.
- Stores application statuses in `jobs/applications.json` and deduplication history in `jobs/seen.json`.
- A separate GitHub Actions workflow polls Telegram callback buttons every 5 minutes and updates the stored status.

## Telegram actions
- **Confirm** marks the vacancy as confirmed for review.
- **Skip** marks it as skipped and removes the buttons.
- **Draft cover letter** sends an English draft based on the role and available job description. Review it and insert the portfolio link before sending.
- **Mark as applied** updates the status to applied.
- Applications are never submitted automatically.

## Required GitHub Secrets
Repository Settings → Secrets and variables → Actions:
- `TELEGRAM_BOT_TOKEN` — token from BotFather.
- `TELEGRAM_CHAT_ID` — your private chat ID. Open the bot and send `/start` before using it.

Do not put secrets in source files or commit them.

## Workflows
- `.github/workflows/myshka-jobs.yml`: daily vacancy search.
- `.github/workflows/myshka-callbacks.yml`: checks Telegram button callbacks every 5 minutes.
- Both workflows share one concurrency group to prevent state-file push conflicts.

## Notes
- Callback processing can take up to 5 minutes because it uses GitHub Actions polling.
- Salary, country eligibility and application requirements must be checked on the employer's page. Some public sources omit these details.
- The cover-letter text is a draft, not an automatically submitted application.
