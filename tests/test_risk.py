"""Tests for risk management pre-trade checks."""
import pytest
from sqlalchemy import select
from bot.database import async_session
from bot.models import RiskConfig


@pytest.mark.asyncio
async def test_risk_config_defaults_disabled():
    from bot.engine.risk import get_risk_config
    config = await get_risk_config()
    # No config yet = None, effectively disabled
    assert config is None or not config.enabled


@pytest.mark.asyncio
async def test_risk_allows_when_disabled():
    from bot.engine.risk import check_pre_trade
    allowed, reason = await check_pre_trade("dca", "buy", "BTC/USD", 100)
    assert allowed is True


@pytest.mark.asyncio
async def test_risk_blocks_when_paused():
    from datetime import datetime, timedelta, timezone
    async with async_session() as session:
        config = RiskConfig(
            enabled=True,
            paused_until=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        session.add(config)
        await session.commit()

    from bot.engine.risk import check_pre_trade
    allowed, reason = await check_pre_trade("dca", "buy", "BTC/USD", 100)
    assert allowed is False
    assert "pausado" in reason.lower() or "breaker" in reason.lower()
