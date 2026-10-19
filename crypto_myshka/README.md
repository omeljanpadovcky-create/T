# Crypto Myshka OTC paper module

This directory contains a fail-closed research engine and Telegram UI handlers.
It does not place trades.

## Current state

- `otc_signal_engine.py`: SQLite journal, candle validation, duplicate protection,
  result settlement callback, history and aggregate statistics.
- `otc_telegram_handlers.py`: `/otc` menu with Signal, History, Statistics and
  Source Status actions. Signal requests are refused until a real, permitted OTC
  quote adapter is implemented and reviewed.
- No Pocket Option OTC feed adapter is currently registered. Public exchange
  prices must not be relabelled as Pocket Option OTC prices.
- This is not a standalone polling bot. Register its handlers on the existing
  Telegram Application. Do not run a second long-polling process with the same
  token because Telegram only allows one active getUpdates poller per bot.

## Integration

Install the dependency in the environment that runs the existing Telegram app:

```bash
pip install -r crypto_myshka/requirements-otc.txt
```

In the existing application's startup module, add:

```python
from crypto_myshka.otc_telegram_handlers import register_otc_handlers

register_otc_handlers(application)
```

Here `application` must be the existing `python-telegram-bot` Application
before it starts polling or serving its webhook. Do not create a second
Application with the same token.

## Safety and cloud operation

- Do not set a source label to claim a feed is verified. A real adapter must
  provide source identity, timestamps, validated prices, and consistent entry
  and exit quotes before the engine is enabled.
- The handler intentionally refuses to create a signal until that adapter is
  actually implemented and wired into code.
- GitHub Actions scheduled workflows are periodic jobs, not a guaranteed
  continuously running Telegram polling service. For always-on operation, host
  the existing Telegram Application as a persistent worker and configure its
  secrets in that host's environment.
- Never commit bot tokens, API credentials, or private user identifiers.
