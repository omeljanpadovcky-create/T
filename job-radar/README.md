# MYSHKA JOB RADAR

Personal Telegram job-alert bot. It scans remote job APIs, scores 3D/Blender/Game Art roles, and sends the best matches to Telegram.

## Target profile
- Remote: Ukraine, Europe, worldwide
- Roles: 3D Character Artist, Blender Artist, Game Asset Artist, Junior 3D Artist, 3D Modeler, Environment Artist, Prop Artist
- Skills: Blender, Photoshop, Figma, Canva
- English: A2
- Portfolio: approximately 15 projects
- Excludes AI data annotation/trainer roles, sales, unpaid work and unrelated support roles

## Sources
- Remotive public API
- RemoteOK public API
- Arbeitnow public API

## Deploy on Vercel
1. Link this repository to Vercel with the project root set to `job-radar`.
2. Add the environment variables below in Vercel Project Settings → Environment Variables.
3. Redeploy after adding variables.

Required:
- `TELEGRAM_BOT_TOKEN`: token created with Telegram's official @BotFather.
- `TELEGRAM_CHAT_ID`: your private Telegram chat ID.
- `CRON_SECRET`: a long random secret used to protect the scan endpoint.

Recommended for persistent duplicate filtering:
- `UPSTASH_REDIS_REST_URL`
- `UPSTASH_REDIS_REST_TOKEN`

The Redis variables are optional, but without them duplicate filtering cannot persist between serverless runs. With Redis connected, successfully sent listings are remembered for 30 days.

## Telegram setup
1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Run `/newbot`, choose a name and username, then copy the bot token.
3. Open your new bot and send `/start`.
4. Obtain your numeric chat ID using the bot's `getUpdates` endpoint after sending `/start`. Treat the token as a password; never publish it in GitHub or paste it into source files.
5. Add the token and chat ID as Vercel environment variables.

## Schedule and test
- Vercel Hobby schedule: daily at 07:00 UTC (09:00 Kyiv in winter / 10:00 in summer; Hobby may start at any time within that UTC hour).
- Manual test: send a GET or POST request to `/api/check` with header `Authorization: Bearer YOUR_CRON_SECRET`.
- Status: `/api/health`.

The bot does not apply to jobs automatically. It sends links for manual review.
