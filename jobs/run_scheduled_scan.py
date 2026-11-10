"""Run the autonomous MYSHKA vacancy scan and send qualifying Telegram alerts."""
from bot import main as run_vacancy_scan

print("Starting autonomous MYSHKA vacancy scan (Telegram alerts only).")
run_vacancy_scan()
