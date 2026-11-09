"""Poll Telegram actions, then run the scheduled vacancy scan.""" 
from callbacks import main as poll_telegram_callbacks
from bot import main as run_vacancy_scan

print("Starting scheduled MYSHKA run: Telegram callbacks first.")
poll_telegram_callbacks()
print("Starting scheduled MYSHKA vacancy scan.")
run_vacancy_scan()
