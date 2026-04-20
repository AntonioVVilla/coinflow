from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool
from bot.config import settings


class Base(DeclarativeBase):
    pass


# In-memory SQLite URLs (used in tests) need StaticPool so every session shares
# the same underlying connection — otherwise each checkout opens a fresh empty
# DB and the tables created by init_db disappear.
_engine_kwargs: dict = {"echo": False}
if ":memory:" in settings.database_url:
    _engine_kwargs.update(poolclass=StaticPool, connect_args={"check_same_thread": False})

engine = create_async_engine(settings.database_url, **_engine_kwargs)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db():
    async with engine.begin() as conn:
        from bot import models  # noqa: F401
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
    logger = logging.getLogger("bot.db_migrate")

    migrations = list(_SAFE_MIGRATIONS)

    async with engine.begin() as conn:
        for table, column, definition in migrations:
            if (table, column, definition) not in _SAFE_MIGRATIONS:
                raise RuntimeError(f"Migration not in allowlist: {table}.{column}")
            try:
                await conn.execute(
                    __import__("sqlalchemy").text(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                )
                logger.info(f"Migration: added {table}.{column}")
            except Exception as e:
                if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                    pass  # Column already exists, skip
                else:
                    logger.debug(f"Migration {table}.{column} skipped: {e}")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
