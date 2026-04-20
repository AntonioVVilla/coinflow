"""Tests for engine runner (strategy management)."""
import pytest
from bot.engine.runner import (
    get_exchange_client,
    init_exchange,
    start_strategy,
    stop_strategy,
    get_strategy_status,
    get_all_statuses,
    force_tick,
    kill_switch,
    STRATEGY_CLASSES,
)
from bot.exchange.schemas import Ticker


class MockExchangeClient:
    """Mock exchange for testing."""
    def __init__(self):
        self.closed = False

    async def close(self):
        self.closed = True

    async def fetch_ticker(self, symbol):
        return Ticker(symbol=symbol, last=50000, bid=49990, ask=50010, high=51000, low=49000, timestamp=0)

    async def fetch_balance(self):
        return []


@pytest.mark.asyncio
async def test_init_exchange_paper_mode():
    await init_exchange("", "")
    client = get_exchange_client()
    assert client is not None


@pytest.mark.asyncio
async def test_start_strategy_adds_to_active():
    await init_exchange("", "")
    result = await start_strategy("dca", "BTC/USD", {"amount_usd": 10, "interval_hours": 24})
    assert result is True


@pytest.mark.asyncio
async def test_start_strategy_fails_unknown():
    await init_exchange("", "")
    result = await start_strategy("unknown_strategy", "BTC/USD", {})
    assert result is False


@pytest.mark.asyncio
async def test_stop_strategy_removes_from_active():
    await init_exchange("", "")
    await start_strategy("dca", "BTC/USD", {"amount_usd": 10, "interval_hours": 24})
    result = await stop_strategy("dca")
    assert result is True


@pytest.mark.asyncio
async def test_stop_strategy_returns_false_if_not_running():
    await init_exchange("", "")
    result = await stop_strategy("dca")
    assert result is False


@pytest.mark.asyncio
async def test_get_strategy_status_returns_running():
    await init_exchange("", "")
    await start_strategy("dca", "BTC/USD", {"amount_usd": 10, "interval_hours": 24})
    status = get_strategy_status("dca")
    assert status is not None
    assert status.get("running") is True


@pytest.mark.asyncio
async def test_get_strategy_status_returns_none_if_not_running():
    await init_exchange("", "")
    from bot.engine import runner
    runner._active_strategies.clear()
    status = get_strategy_status("dca")
    assert status is None


@pytest.mark.asyncio
async def test_get_all_statuses_returns_dict():
    await init_exchange("", "")
    await start_strategy("dca", "BTC/USD", {"amount_usd": 10, "interval_hours": 24})
    statuses = get_all_statuses()
    assert isinstance(statuses, dict)
    assert "dca" in statuses


@pytest.mark.asyncio
async def test_force_tick_returns_error_structure():
    await init_exchange("", "")
    result = await force_tick("dca")
    assert "ok" in result
    assert "error" in result


@pytest.mark.asyncio
async def test_force_tick_error_not_running():
    result = await force_tick("nonexistent")
    assert result.get("ok") is False
    assert "no esta corriendo" in result.get("error", "").lower()


@pytest.mark.asyncio
async def test_kill_switch_stops_all(monkeypatch):
    # Replace the real PaperClient (which drives ccxt → live Coinbase) with a
    # mock so kill_switch() does not try to cancel open orders against the
    # network – that branch is skipped when the client has no `_exchange`.
    from bot.engine import runner as runner_mod

    await init_exchange("", "")
    monkeypatch.setattr(runner_mod, "_exchange_client", MockExchangeClient())
    await start_strategy("dca", "BTC/USD", {"amount_usd": 10, "interval_hours": 24})
    await start_strategy("grid", "ETH/USD", {"lower_price": 1000, "upper_price": 2000, "num_grids": 3, "amount_per_grid": 0.01})

    result = await kill_switch()
    assert "dca" in result.get("stopped_strategies", [])
    assert "grid" in result.get("stopped_strategies", [])


@pytest.mark.asyncio
async def test_strategy_classes_contains_expected():
    assert "grid" in STRATEGY_CLASSES
    assert "dca" in STRATEGY_CLASSES
    assert "webhook" in STRATEGY_CLASSES