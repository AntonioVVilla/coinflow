"""Tests for trading strategies."""
import pytest
from bot.strategies.dca import DCAStrategy
from bot.strategies.grid import GridStrategy
from bot.strategies.webhook import WebhookStrategy
from bot.exchange.schemas import Ticker


def make_ticker(symbol="BTC/USD", price=50000):
    return Ticker(symbol=symbol, last=price, bid=price, ask=price, high=price, low=price, timestamp=0)


@pytest.mark.asyncio
async def test_dca_setup_loads_empty_counters():
    s = DCAStrategy()
    await s.setup({"amount_usd": 10, "symbol": "BTC/USD"})
    assert s.num_buys == 0
    assert s.total_invested == 0
    assert s.amount_usd == 10
    assert s.symbol == "BTC/USD"


@pytest.mark.asyncio
async def test_dca_tick_emits_buy_order():
    s = DCAStrategy()
    await s.setup({"amount_usd": 10, "symbol": "BTC/USD"})
    orders = await s.tick(make_ticker("BTC/USD", 50000))
    assert len(orders) == 1
    assert orders[0].side == "buy"
    assert orders[0].order_type == "market"
    assert orders[0].cost == 10
    assert orders[0].amount == pytest.approx(10 / 50000)


@pytest.mark.asyncio
async def test_dca_handles_zero_price():
    s = DCAStrategy()
    await s.setup({"amount_usd": 10})
    orders = await s.tick(make_ticker(price=0))
    assert orders == []


@pytest.mark.asyncio
async def test_grid_setup_computes_levels():
    s = GridStrategy()
    await s.setup({
        "lower_price": 40000, "upper_price": 50000,
        "num_grids": 5, "amount_per_grid": 0.001, "symbol": "BTC/USD",
    })
    assert len(s.grid_levels) == 6  # num_grids + 1
    assert s.grid_levels[0] == 40000
    assert s.grid_levels[-1] == 50000
    assert s.grid_levels[1] - s.grid_levels[0] == pytest.approx(2000)


@pytest.mark.asyncio
async def test_grid_no_orders_outside_range():
    s = GridStrategy()
    await s.setup({"lower_price": 40000, "upper_price": 50000, "num_grids": 5, "amount_per_grid": 0.001})
    # First tick always establishes last_price, no orders
    orders = await s.tick(make_ticker(price=35000))
    assert orders == []


@pytest.mark.asyncio
async def test_grid_buy_on_downward_cross():
    s = GridStrategy()
    await s.setup({"lower_price": 40000, "upper_price": 50000, "num_grids": 5, "amount_per_grid": 0.001})
    # First tick at 45000 to set last_price
    await s.tick(make_ticker(price=45000))
    # Next tick at 43500 crosses 44000 downward -> buy
    orders = await s.tick(make_ticker(price=43500))
    assert len(orders) >= 1
    assert all(o.side == "buy" for o in orders)


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_passphrase():
    s = WebhookStrategy()
    await s.setup({"passphrase": "secret", "default_amount_usd": 50, "symbol": "BTC/USD"})
    order = s.execute_signal({"action": "buy", "passphrase": "wrong"}, 50000)
    assert order is None


@pytest.mark.asyncio
async def test_webhook_accepts_valid_passphrase():
    s = WebhookStrategy()
    await s.setup({"passphrase": "secret", "default_amount_usd": 50, "symbol": "BTC/USD"})
    order = s.execute_signal({"action": "buy", "passphrase": "secret"}, 50000)
    assert order is not None
    assert order.side == "buy"
    assert order.order_type == "market"
