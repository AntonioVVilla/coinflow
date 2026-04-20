"""Pytest configuration: async support + test DB."""
import os
import pytest
from cryptography.fernet import Fernet

# Use in-memory SQLite for tests
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()  # Valid Fernet key
os.environ["PAPER_MODE"] = "true"


@pytest.fixture(autouse=True)
async def init_test_db():
    """Give each test a fresh DB + clean runner state.

    StaticPool shares the same SQLite :memory: connection across sessions, so
    trades created by one test would otherwise leak into the next. We drop
    and recreate the schema per test, and also clear the runner module's
    global `_active_strategies` dict so a strategy started in one test does
    not linger into the next one.
    """
    from bot.database import Base, engine, init_db
    from bot.engine import runner

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await init_db()
    runner._active_strategies.clear()
    yield
    runner._active_strategies.clear()
