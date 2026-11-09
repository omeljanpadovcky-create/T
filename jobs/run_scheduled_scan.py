"""Run the scheduled vacancy scan. Telegram updates are handled by the Vercel webhook."""
from bot import main as run_vacancy_scan

print("Starting scheduled MYSHKA vacancy scan.")
run_vacancy_scan()
