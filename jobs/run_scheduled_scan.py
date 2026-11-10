"""Run the scheduled MYSHKA vacancy scan and process Telegram review buttons."""
from bot import main as run_vacancy_scan
from callbacks import main as process_telegram_updates

print("Starting MYSHKA vacancy scan and Telegram delivery.")
run_vacancy_scan()

print("Processing Telegram button callbacks.")
process_telegram_updates()
