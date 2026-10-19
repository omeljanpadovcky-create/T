# Crypto Myshka cloud worker

This Render Blueprint runs the existing long-lived Telegram/P2P radar process as a persistent worker. It does not create real trades.

## Deploy
1. In Render, create a new Blueprint from this repository and select `render.yaml`.
2. Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as secret/environment values in the Render dashboard. Never commit tokens to GitHub.
3. Deploy the worker and inspect its logs.
4. Before enabling this worker, stop any local copy using the same Telegram bot token. Telegram polling with one token must have a single active consumer.

## OTC limitation
The OTC Telegram menu is only an interface at this stage. Pocket Option OTC quote acquisition is not implemented or verified, so `/otc_signal` intentionally refuses to generate a direction. The paper engine does not place trades. Do not represent ordinary exchange candles as Pocket Option OTC prices.

## Runtime and cost
A persistent worker is required for continuous operation; this blueprint uses Render's `starter` worker plan, which may incur charges. Deployment is not complete until you create the Render service, add secrets, and verify its logs and Telegram response.
