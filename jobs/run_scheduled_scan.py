"""Run the scheduled MYSHKA vacancy scan; no Telegram button polling."""
from bot import main as run_vacancy_scan

print("Starting MYSHKA vacancy scan and Telegram delivery.")
run_vacancy_scan()
