"""Run only the scheduled MYSHKA vacancy scan; no Telegram button polling."""
from bot import main as run_vacancy_scan

print("Starting scheduled MYSHKA vacancy scan.")
run_vacancy_scan()
