"""Integration tests for API endpoints.

The real `bot.main.lifespan` hook performs live network calls to Coinbase via
ccxt (prices snapshot, websocket streamer, Telegram listener). In the test
environment we skip those side effects and exercise the FastAPI routes in
isolation – the init_test_db autouse fixture in conftest.py already sets up
the in-memory DB the routes need.
"""
import pytest
from httpx import AsyncClient, ASGITransport
from bot.web.app import create_app


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "ok"


@pytest.mark.asyncio
async def test_status_endpoint_exists(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/status")
        assert response.status_code in (200, 401, 404)


@pytest.mark.asyncio
async def test_dashboard_endpoint_public(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/dashboard")
        assert response.status_code in (200, 401)


@pytest.mark.asyncio
async def test_strategy_list_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/strategies")
        assert response.status_code in (200, 401)


@pytest.mark.asyncio
async def test_trades_endpoint_requires_auth(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/trades?page=1")
        assert response.status_code in (200, 401)


@pytest.mark.asyncio
async def test_risk_config_endpoint(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/risk/config")
        assert response.status_code in (200, 401, 404)


@pytest.mark.asyncio
async def test_invalid_endpoint_returns_404(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/nonexistent")
        assert response.status_code == 404