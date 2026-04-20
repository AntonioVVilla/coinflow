from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.pool import StaticPool
from bot.config import settings
from bot.db_base import Base

__all__ = ["Base", "engine", "async_session", "init_db", "get_session"]


# In-memory SQLite URLs (used in tests) need StaticPool so every session shares
# the same underlying connection — otherwise each checkout opens a fresh empty
# DB and the tables created by init_db disappear.
_engine_kwargs: dict = {"echo": False}
if ":memory:" in settings.database_url:
    _engine_kwargs.update(poolclass=StaticPool, connect_args={"check_same_thread": False})

engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    # Local import: registers every ORM class with Base.metadata without
    # creating a module-level dependency from bot.database -> bot.models.
    from bot import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Lightweight migrations: add columns that may be missing on older DBs
    await _run_migrations()


_SAFE_MIGRATIONS: set[tuple[str, str, str]] = {
    ("portfolio_snapshots", "is_paper", "BOOLEAN DEFAULT 0"),
    # Future migrations go here as (table, column, definition) tuples
}


async def _run_migrations():
    """Add missing columns to existing tables (SQLite ALTER TABLE)."""
    import logging
    from sqlalchemy import text

    logger = logging.getLogger("bot.db_migrate")

    # Each migration tuple is constructed from the hard-coded allowlist, so the
    # table/column/definition values are trusted constants rather than user
    # input; that's what keeps the raw ALTER TABLE out of py/sql-injection.
    async with engine.begin() as conn:
        for table, column, definition in sorted(_SAFE_MIGRATIONS):
            if (table, column, definition) not in _SAFE_MIGRATIONS:
                raise RuntimeError("Migration not in allowlist")
            try:
                await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}"))
                logger.info("Migration: added %s.%s", table, column)
            except Exception as e:
                msg = str(e).lower()
                if "duplicate column" in msg or "already exists" in msg:
                    continue  # Column already exists, skip
                logger.debug("Migration %s.%s skipped: %s", table, column, e)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
