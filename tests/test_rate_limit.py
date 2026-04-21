"""Sanity tests for the slowapi rate limiter on public endpoints.

The `limiter` from bot.web.rate_limit is a module-level singleton, so to keep
each test isolated we reset its internal counters before every run.
"""
import pytest
from httpx import AsyncClient, ASGITransport

from bot.web.app import create_app
from bot.web.rate_limit import limiter


@pytest.fixture(autouse=True)
def _reset_limiter():
    limiter.reset()
    yield
    limiter.reset()


@pytest.fixture
def client_factory():
    def _make() -> AsyncClient:
        app = create_app()
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return _make


@pytest.mark.asyncio
async def test_login_rate_limiter_trips_after_five_attempts(client_factory):
    """/api/auth/login is 5/min; the 6th call from the same client hits 429."""
    async with client_factory() as client:
        # First five calls get the normal 400 (auth is not enabled in the test
        # DB) — what we care about is that they don't get 429 yet.
        for _ in range(5):
            resp = await client.post("/api/auth/login", json={"password": "x"})
            assert resp.status_code != 429

        resp = await client.post("/api/auth/login", json={"password": "x"})
        assert resp.status_code == 429


@pytest.mark.asyncio
async def test_webhook_rate_limiter_trips_after_burst(client_factory):
    """/api/webhook/tradingview is 30/min; the 31st call is throttled."""
    async with client_factory() as client:
        for _ in range(30):
            resp = await client.post("/api/webhook/tradingview", json={})
            assert resp.status_code != 429

        resp = await client.post("/api/webhook/tradingview", json={})
        assert resp.status_code == 429
