# MYSHKA JOBS

An isolated job-search module. It does not replace the repository's root app.

## What it does
- Searches public remote-job feeds for 3D Artist, 3D Modeler, Prop Artist, Environment Artist, Game Artist and Roblox 3D Artist roles.
- Prioritizes junior and entry-level roles; excludes senior, lead, manager and unpaid roles.
- Checks whether the listing appears open to applicants in Ukraine or worldwide.
- Scores each result against the profile (Blender, 3D modeling, props, environment art, Roblox/game art).
- Sends matching listings to Telegram and stores sent IDs to avoid duplicates.

## Required GitHub Actions secrets
- TELEGRAM_BOT_TOKEN — token from BotFather. Never commit it or paste it into chat.
- TELEGRAM_CHAT_ID — the Telegram chat ID where alerts should be delivered.

## Run
The workflow is scheduled every two hours and can also be started manually from GitHub Actions.
