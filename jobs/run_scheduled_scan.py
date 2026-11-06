"""Run the radar at 09:00 and 16:00 Kyiv time, including DST changes."""
import os
from datetime import datetime
from zoneinfo import ZoneInfo

from bot import main

kyiv_now = datetime.now(ZoneInfo("Europe/Kyiv"))
force = os.environ.get("MYSHKA_FORCE_SCAN", "").lower() == "true"

if force or (kyiv_now.minute < 20 and kyiv_now.hour in {9, 16}):
    print(f"Starting MYSHKA scan at {kyiv_now.isoformat()}")
    main()
else:
    print(f"Skipping hourly tick; Kyiv local time is {kyiv_now.isoformat()}")
