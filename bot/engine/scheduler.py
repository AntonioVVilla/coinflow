import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

from bot.log_utils import safe

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def add_cron_job(job_id: str, func, hour: int = 9, minute: int = 0, **kwargs):
    """Schedule a job at a specific time daily."""
    trigger = CronTrigger(hour=hour, minute=minute)
    scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **kwargs)
    logger.info("Cron job '%s' scheduled daily at %02d:%02d", safe(job_id), hour, minute)


def start_scheduler():
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started")


def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


def add_job(job_id: str, func, seconds: int | None = None, hours: int | None = None, **kwargs):
    if seconds:
        trigger = IntervalTrigger(seconds=seconds)
    elif hours:
        trigger = IntervalTrigger(hours=hours)
    else:
        trigger = IntervalTrigger(seconds=30)

    scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **kwargs)
    logger.info("Job '%s' scheduled (interval: %ss / %sh)", safe(job_id), seconds or 0, hours or 0)


def remove_job(job_id: str):
    try:
        scheduler.remove_job(job_id)
        logger.info("Job '%s' removed", safe(job_id))
    except Exception as err:
        logger.debug("remove_job(%s) ignored: %s", safe(job_id), safe(err))
