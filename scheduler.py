# scheduler.py

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from worker import worker

logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler()


async def start_scheduler():
    scheduler.add_job(
        worker,
        CronTrigger(hour=1),
        id="jiomart_price_updater",
        name="JioMart Price Updater",
        replace_existing=True,
    )
    scheduler.start()
