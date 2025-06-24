# scheduler.py

import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from worker import worker

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def start_scheduler():
    scheduler.add_job(
        worker,
        IntervalTrigger(hours=1, timezone="Asia/Kolkata"),
        id="jiomart_price_updater",
        name="JioMart Price Updater",
        # next_run_time=datetime.now(),
        replace_existing=True,
    )
    scheduler.start()
