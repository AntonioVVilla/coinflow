"""Tests for stop-loss / take-profit logic on the DCA strategy.

The logic lives in `DCAStrategy.evaluate_sl_tp` (synchronous, pure-ish): it
reads `self.avg_buy_price`, `self.net_bought`, `self.stop_loss_pct`,
`self.take_profit_pct`, and returns the sell orders the runner should
execute. Tests bypass the DB by driving these attributes directly.
"""
import time

import pytest
from httpx import ASGITransport, AsyncClient

from bot.exchange.schemas import Ticker
from bot.strategies.dca import DCAStrategy
from bot.web.app import create_app


def _ticker(price: float) -> Ticker:
    return Ticker(
        symbol="BTC/USD", last=price, bid=price, ask=price,
        high=price, low=price, timestamp=0,
    )


def _strategy(*, sl: float = 0.0, tp: float = 0.0, avg: float = 100.0,
              net: float = 1.0) -> DCAStrategy:
    s = DCAStrategy()
    s.stop_loss_pct = sl
    s.take_profit_pct = tp
    # Seed internal counters directly to bypass DB lookups.
    s.total_invested = avg * net
    s.total_bought = net
    s.total_sold = 0.0
    s.symbol = "BTC/USD"
    return s


def test_sl_triggers_when_price_drops_below_threshold():
    s = _strategy(sl=5.0, avg=100.0, net=1.0)
    orders = s.evaluate_sl_tp(_ticker(94.0))  # -6% < -5%
    assert len(orders) == 1
    assert orders[0].side == "sell"
    assert orders[0].amount == 1.0
    assert orders[0].metadata["trigger"] == "stop_loss"


def test_sl_does_not_trigger_just_above_threshold():
    s = _strategy(sl=5.0, avg=100.0, net=1.0)
    orders = s.evaluate_sl_tp(_ticker(95.5))  # -4.5% > -5%
    assert orders == []


def test_tp_triggers_when_price_rises_above_threshold():
    s = _strategy(tp=10.0, avg=100.0, net=1.0)
    orders = s.evaluate_sl_tp(_ticker(111.0))
    assert len(orders) == 1
    assert orders[0].metadata["trigger"] == "take_profit"


def test_no_trigger_when_sl_and_tp_both_disabled():
    s = _strategy(sl=0.0, tp=0.0, avg=100.0, net=1.0)
    assert s.evaluate_sl_tp(_ticker(1.0)) == []
    assert s.evaluate_sl_tp(_ticker(1e6)) == []


def test_no_trigger_when_position_is_zero():
    s = _strategy(sl=5.0, tp=10.0, avg=100.0, net=0.0)
    assert s.evaluate_sl_tp(_ticker(50.0)) == []
    assert s.evaluate_sl_tp(_ticker(200.0)) == []


def test_cooldown_prevents_retrigger_immediately():
    s = _strategy(sl=5.0, avg=100.0, net=1.0)
    first = s.evaluate_sl_tp(_ticker(94.0))
    assert len(first) == 1
    # Still below the trigger; cooldown must suppress.
    second = s.evaluate_sl_tp(_ticker(93.0))
    assert second == []


def test_cooldown_expires_after_window(monkeypatch):
    s = _strategy(sl=5.0, avg=100.0, net=1.0)
    first = s.evaluate_sl_tp(_ticker(94.0))
    assert len(first) == 1
    # Simulate time passing beyond the 5 min cooldown.
    original_time = time.time
    monkeypatch.setattr(time, "time", lambda: original_time() + 10_000)
    # Also seed a new "net bought" since the sell would have cleared the
    # position in production.
    s.total_bought = 1.0
    s.total_sold = 0.0
    second = s.evaluate_sl_tp(_ticker(80.0))
    assert len(second) == 1


def test_ignores_non_positive_price():
    s = _strategy(sl=5.0, avg=100.0, net=1.0)
    assert s.evaluate_sl_tp(_ticker(0.0)) == []


# ---------------------------------------------------------------------------
# API-level validation on PUT /api/strategies/{name}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_api_rejects_stop_loss_out_of_range():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "symbol": "BTC/USD",
            "params": {
                "amount_usd": 10, "interval_hours": 24,
                "stop_loss_pct": 200,  # way over 50
            },
        }
        resp = await client.put("/api/strategies/dca", json=payload)
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_api_accepts_valid_sl_tp():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "symbol": "BTC/USD",
            "params": {
                "amount_usd": 10, "interval_hours": 24,
                "stop_loss_pct": 5, "take_profit_pct": 10,
            },
        }
        resp = await client.put("/api/strategies/dca", json=payload)
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_rejects_non_numeric_sl():
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        payload = {
            "symbol": "BTC/USD",
            "params": {
                "amount_usd": 10, "interval_hours": 24,
                "stop_loss_pct": "banana",
            },
        }
        resp = await client.put("/api/strategies/dca", json=payload)
        assert resp.status_code == 400
