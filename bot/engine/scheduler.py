import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def add_cron_job(job_id: str, func, hour: int = 9, minute: int = 0, **kwargs):
    """Schedule a job at a specific time daily."""
    trigger = CronTrigger(hour=hour, minute=minute)
    scheduler.add_job(func, trigger, id=job_id, replace_existing=True, **kwargs)
    logger.info(f"Cron job '{job_id}' scheduled daily at {hour:02d}:{minute:02d}")


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
    logger.info(f"Job '{job_id}' scheduled (interval: {seconds or 0}s / {hours or 0}h)")


def remove_job(job_id: str):
    try:
        scheduler.remove_job(job_id)
        logger.info(f"Job '{job_id}' removed")
    except Exception as err:
        logger.debug(f"remove_job({job_id}) ignored: {err}")
