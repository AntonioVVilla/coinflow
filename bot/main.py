import logging
from contextlib import asynccontextmanager

import uvicorn
from bot.config import settings
from bot.database import init_db, async_session
from bot.models import ApiKey
from bot.security import decrypt
from bot.engine.runner import init_exchange, load_active_strategies
from bot.engine.scheduler import start_scheduler, stop_scheduler, add_job, add_cron_job
from bot.engine.snapshots import take_snapshot
from bot.engine.risk import check_circuit_breaker
from bot.engine.daily_summary import send_daily_summary
from bot.web.app import create_app
from sqlalchemy import select


def setup_logging():
    log_dir = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(str(log_dir / "bot.log")),
        ],
    )


async def startup():
    logger = logging.getLogger("bot")

    # Ensure data directory exists
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    # Init database
    await init_db()
    logger.info("Database initialized")

    # Load persisted mode preference from DB
    from bot.system_config import get_config, set_config

    api_key = ""
    api_secret = ""  # nosec B105 - placeholder for unset exchange credentials
    async with async_session() as session:
        result = await session.execute(
            select(ApiKey).where(ApiKey.exchange == "coinbase", ApiKey.is_valid.is_(True))
        )
        key_row = result.scalar_one_or_none()
        if key_row:
            api_key = decrypt(key_row.api_key_enc)
            api_secret = decrypt(key_row.api_secret_enc)

    # Determine mode: DB preference > auto-detect > env default
    persisted_mode = await get_config("paper_mode", "")
    if persisted_mode:
        # User explicitly set a mode before - respect it
        settings.paper_mode = persisted_mode.lower() == "true"
        logger.info(f"Mode loaded from DB: {'PAPER' if settings.paper_mode else 'LIVE'}")
    elif api_key:
        # First run with keys but no prior mode choice - default to LIVE
        settings.paper_mode = False
        await set_config("paper_mode", "false")
        logger.info("API keys found, no prior mode - defaulting to LIVE")
    # else: stays as env default (PAPER)

    # Init exchange client
    await init_exchange(api_key, api_secret)

    # Start scheduler and load active strategies
    start_scheduler()
    await load_active_strategies()

    # Schedule periodic portfolio snapshots (every 5 min)
    add_job("portfolio_snapshot", take_snapshot, seconds=300)
    # Circuit breaker check every 5 min
    add_job("circuit_breaker", check_circuit_breaker, seconds=300)
    # Daily summary at 9:00 local time
    add_cron_job("daily_summary", send_daily_summary, hour=9, minute=0)
    # Session cleanup every 5 min
    from bot.auth import cleanup_expired_sessions
    add_job("session_cleanup", cleanup_expired_sessions, seconds=300)
    # Take an initial snapshot immediately
    await take_snapshot()

    # Start WebSocket price streamer
    from bot.web.routes.websocket import start_streamer
    start_streamer()

    # Start Telegram command listener (only polls when config is enabled)
    from bot.notifications.telegram_listener import start_listener
    start_listener()

    logger.info(f"CryptoBot started (paper_mode={settings.paper_mode})")


async def shutdown():
    logger = logging.getLogger("bot")
    stop_scheduler()
    logger.info("CryptoBot stopped")


@asynccontextmanager
async def lifespan(app):
    await startup()
    yield
    await shutdown()


def main():
    setup_logging()

    app = create_app()
    app.router.lifespan_context = lifespan

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
