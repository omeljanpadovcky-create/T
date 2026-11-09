"""Poll Telegram actions and run the scheduled vacancy scan independently."""
from callbacks import main as poll_telegram_callbacks
from bot import main as run_vacancy_scan

errors = []

print("Starting scheduled MYSHKA run: Telegram callbacks first.")
try:
    poll_telegram_callbacks()
except Exception as exc:
    errors.append(("Telegram callbacks", exc))
    print(f"Telegram callback polling failed; continuing with vacancy scan: {type(exc).__name__}: {exc}")

print("Starting scheduled MYSHKA vacancy scan.")
try:
    run_vacancy_scan()
except Exception as exc:
    errors.append(("vacancy scan", exc))
    print(f"Vacancy scan failed: {type(exc).__name__}: {exc}")

if errors:
    summary = "; ".join(f"{name}: {type(exc).__name__}" for name, exc in errors)
    raise RuntimeError("MYSHKA run completed with errors: " + summary)
