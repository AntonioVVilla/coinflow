"""Alembic migration environment.

Uses a *synchronous* SQLAlchemy engine on purpose. Alembic is only ever
invoked at startup (via `init_db`) or by one-off `docker compose run
alembic ...` commands; neither needs async. Going through
`async_engine_from_config` + `asyncio.run` from inside `asyncio.to_thread`
was deadlocking against the app's own async engine when both pointed at
the same SQLite file.

The app's runtime engine stays async (see `bot.database`). This module only
runs DDL migrations, which are synchronous by nature.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from alembic import context

from bot.config import settings
from bot.db_base import Base
from bot import models  # noqa: F401 — registers every ORM class on Base.metadata

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Always drive migrations with the live app URL so prod/dev/test are
# consistent. Alembic itself runs synchronously, so strip any async driver
# marker from the URL (e.g. sqlite+aiosqlite:// → sqlite://) to avoid
# dragging aiosqlite into the migration path.
_runtime_url = settings.database_url
_sync_url = (
    _runtime_url
    .replace("sqlite+aiosqlite://", "sqlite://")
    .replace("postgresql+asyncpg://", "postgresql+psycopg://")
)
config.set_main_option("sqlalchemy.url", _sync_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation)."""
    context.configure(
        url=_sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite needs batch mode for ALTER TABLE
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        do_run_migrations(connection)

    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
