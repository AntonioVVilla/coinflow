"""Tests for risk management pre-trade checks."""
import pytest
from sqlalchemy import select
from bot.database import async_session
from bot.models import RiskConfig


@pytest.mark.asyncio
async def test_risk_config_defaults_disabled():
    from bot.engine.risk import get_risk_config
    config = await get_risk_config()
    assert config is None or not config.enabled


@pytest.mark.asyncio
async def test_risk_allows_when_no_config():
    from bot.engine.risk import check_pre_trade
    allowed, reason = await check_pre_trade("dca", "buy", "BTC/USD", 100)
    assert allowed is True
    assert reason == ""


@pytest.mark.asyncio
async def test_risk_returns_allowed_for_unconfigured_strategy():
    from bot.engine.risk import check_pre_trade
    result = await check_pre_trade("test_strategy", "buy", "ETH/USD", 50)
    assert result == (True, "")