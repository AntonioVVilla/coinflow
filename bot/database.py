"""Async SQLAlchemy engine + session factory, backed by Alembic migrations.

Tables are now owned by Alembic (see alembic/versions). `init_db` runs
`alembic upgrade head` against the configured database URL, which is
idempotent: fresh DBs get the full schema, existing DBs only get any pending
migrations.

Tests run against `sqlite+aiosqlite:///:memory:` and need a StaticPool so all
sessions share the one in-memory connection — otherwise each checkout opens a
brand-new empty DB and the migration tables vanish from later queries.
"""
import logging
from collections.abc import AsyncGenerator
from pathlib import Path

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from bot.config import settings
from bot.db_base import Base

__all__ = ["Base", "engine", "async_session", "init_db", "get_session"]

logger = logging.getLogger(__name__)

_engine_kwargs: dict = {"echo": False}
if ":memory:" in settings.database_url:
    _engine_kwargs.update(poolclass=StaticPool, connect_args={"check_same_thread": False})

engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"


def _alembic_config() -> AlembicConfig:
    cfg = AlembicConfig(str(_ALEMBIC_INI))
    cfg.set_main_option("sqlalchemy.url", settings.database_url)
    return cfg


def _run_upgrade_sync() -> None:
    """Apply every pending migration up to head."""
    command.upgrade(_alembic_config(), "head")


async def init_db() -> None:
    """Bring the database schema up to the latest Alembic revision.

    For the in-memory test DB, Alembic would open a *second* connection (so its
    CREATE TABLE statements would land in a different throwaway database and
    disappear). In that case we fall back to `metadata.create_all` on the same
    engine instance — the only production path that keeps hitting this branch
    is the unit-test harness.
    """
    # Register every ORM class against Base.metadata without creating a
    # module-level cycle between bot.database and bot.models.
    from bot import models  # noqa: F401

    if ":memory:" in settings.database_url:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.debug("init_db: created schema in-memory (bypassing Alembic)")
        return

    import asyncio

    await asyncio.to_thread(_run_upgrade_sync)
    logger.info("init_db: schema upgraded to head via Alembic")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
