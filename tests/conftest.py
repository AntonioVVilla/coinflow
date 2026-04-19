"""Pytest configuration: async support + test DB."""
import asyncio
import os
import pytest
from cryptography.fernet import Fernet

# Use in-memory SQLite for tests
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()  # Valid Fernet key
os.environ["PAPER_MODE"] = "true"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def init_test_db():
    from bot.database import init_db
    await init_db()
    yield
