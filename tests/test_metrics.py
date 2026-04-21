"""Unit tests for the shared performance analytics module."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from bot.engine.metrics import (
    MIN_SAMPLES_FOR_ANNUALISATION,
    portfolio_stats,
    realized_pnl_fifo,
)


@dataclass
class FakeTrade:
    strategy: str
    symbol: str
    side: str
    amount: float
    price: float
    cost: float
    fee: float
    created_at: datetime


@dataclass
class FakeSnapshot:
    total_usd: float
    snapshot_at: datetime


_T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _t(offset_seconds: int) -> datetime:
    return _T0 + timedelta(seconds=offset_seconds)


# ---------------------------------------------------------------------------
# FIFO realized P&L
# ---------------------------------------------------------------------------


def test_fifo_single_buy_single_sell_full_match():
    trades = [
        FakeTrade("dca", "BTC/USD", "buy", 1.0, 100.0, 100.0, 1.0, _t(0)),
        FakeTrade("dca", "BTC/USD", "sell", 1.0, 120.0, 120.0, 1.2, _t(3600)),
    ]
    result = realized_pnl_fifo(trades)
    stats = result["by_key"]["dca|BTC/USD"]
    # Effective buy price = 100 + 1 = 101. Net sell price = 120 - 1.2 = 118.8.
    # Realized = (118.8 - 101) * 1.0 = 17.8
    assert abs(stats["realized_pnl"] - 17.8) < 1e-6
    assert stats["trades_matched"] == 1
    assert stats["wins"] == 1
    assert stats["losses"] == 0
    assert stats["unmatched_sell_amount"] == 0.0
    assert stats["avg_hold_seconds"] == 3600.0


def test_fifo_single_sell_consumes_multiple_buys():
    # Two buys of 0.5 at different prices, one sell of 1.0
    trades = [
        FakeTrade("dca", "BTC/USD", "buy", 0.5, 100.0, 50.0, 0.0, _t(0)),
        FakeTrade("dca", "BTC/USD", "buy", 0.5, 110.0, 55.0, 0.0, _t(1800)),
        FakeTrade("dca", "BTC/USD", "sell", 1.0, 120.0, 120.0, 0.0, _t(3600)),
    ]
    result = realized_pnl_fifo(trades)
    stats = result["by_key"]["dca|BTC/USD"]
    # (120 - 100) * 0.5 + (120 - 110) * 0.5 = 10 + 5 = 15
    assert abs(stats["realized_pnl"] - 15.0) < 1e-6
    assert stats["trades_matched"] == 1
    # Hold weighted: (3600 * 0.5 + 1800 * 0.5) / 1.0 = 2700
    assert abs(stats["avg_hold_seconds"] - 2700.0) < 1e-6


def test_fifo_partial_sell_leaves_lot_open():
    trades = [
        FakeTrade("dca", "BTC/USD", "buy", 1.0, 100.0, 100.0, 0.0, _t(0)),
        FakeTrade("dca", "BTC/USD", "sell", 0.4, 150.0, 60.0, 0.0, _t(3600)),
        FakeTrade("dca", "BTC/USD", "sell", 0.2, 160.0, 32.0, 0.0, _t(7200)),
    ]
    result = realized_pnl_fifo(trades)
    stats = result["by_key"]["dca|BTC/USD"]
    # 1st sell: (150 - 100) * 0.4 = 20
    # 2nd sell: (160 - 100) * 0.2 = 12
    assert abs(stats["realized_pnl"] - 32.0) < 1e-6
    assert stats["trades_matched"] == 2
    assert stats["wins"] == 2
    assert stats["unmatched_sell_amount"] == 0.0


def test_fifo_sell_without_buy_becomes_unmatched():
    trades = [
        FakeTrade("grid", "BTC/USD", "sell", 0.3, 100.0, 30.0, 0.0, _t(0)),
    ]
    result = realized_pnl_fifo(trades)
    stats = result["by_key"]["grid|BTC/USD"]
    assert stats["realized_pnl"] == 0.0
    assert stats["trades_matched"] == 0
    assert stats["unmatched_sell_amount"] == 0.3


def test_fifo_mixed_matched_and_unmatched_sell():
    trades = [
        FakeTrade("grid", "BTC/USD", "buy", 0.2, 100.0, 20.0, 0.0, _t(0)),
        FakeTrade("grid", "BTC/USD", "sell", 0.5, 120.0, 60.0, 0.0, _t(3600)),
    ]
    result = realized_pnl_fifo(trades)
    stats = result["by_key"]["grid|BTC/USD"]
    # 0.2 matched at (120 - 100) = 4 realized. 0.3 unmatched.
    assert abs(stats["realized_pnl"] - 4.0) < 1e-6
    assert stats["trades_matched"] == 1
    assert abs(stats["unmatched_sell_amount"] - 0.3) < 1e-6


def test_fifo_per_key_segregation():
    trades = [
        FakeTrade("dca", "BTC/USD", "buy", 1.0, 100.0, 100.0, 0.0, _t(0)),
        FakeTrade("grid", "BTC/USD", "buy", 1.0, 100.0, 100.0, 0.0, _t(1)),
        FakeTrade("dca", "BTC/USD", "sell", 1.0, 110.0, 110.0, 0.0, _t(2)),
    ]
    result = realized_pnl_fifo(trades)
    # Only dca matched. Grid still has an open lot, no sells there.
    assert "dca|BTC/USD" in result["by_key"]
    assert "grid|BTC/USD" not in result["by_key"]
    assert abs(result["by_key"]["dca|BTC/USD"]["realized_pnl"] - 10.0) < 1e-6
    assert abs(result["global"]["realized_pnl"] - 10.0) < 1e-6


def test_fifo_losing_trade_classified_as_loss():
    trades = [
        FakeTrade("dca", "BTC/USD", "buy", 1.0, 100.0, 100.0, 0.0, _t(0)),
        FakeTrade("dca", "BTC/USD", "sell", 1.0, 80.0, 80.0, 0.0, _t(3600)),
    ]
    result = realized_pnl_fifo(trades)
    stats = result["by_key"]["dca|BTC/USD"]
    assert stats["realized_pnl"] == -20.0
    assert stats["losses"] == 1
    assert stats["wins"] == 0


def test_fifo_ignores_zero_amount_trades():
    trades = [
        FakeTrade("dca", "BTC/USD", "buy", 0.0, 100.0, 0.0, 0.0, _t(0)),
        FakeTrade("dca", "BTC/USD", "buy", 1.0, 100.0, 100.0, 0.0, _t(1)),
        FakeTrade("dca", "BTC/USD", "sell", 1.0, 110.0, 110.0, 0.0, _t(2)),
    ]
    result = realized_pnl_fifo(trades)
    stats = result["by_key"]["dca|BTC/USD"]
    assert stats["trades_matched"] == 1
    assert abs(stats["realized_pnl"] - 10.0) < 1e-6


# ---------------------------------------------------------------------------
# Portfolio equity stats
# ---------------------------------------------------------------------------


def _snap(days_ago: int, value: float) -> FakeSnapshot:
    return FakeSnapshot(total_usd=value, snapshot_at=_T0 + timedelta(days=-days_ago))


def test_portfolio_stats_empty_returns_zero():
    result = portfolio_stats([], days=30)
    assert result["sharpe"] is None
    assert result["sortino"] is None
    assert result["n_samples"] == 0
    assert result["insufficient_data"] is True
    assert result["max_drawdown_pct"] == 0.0


def test_portfolio_stats_single_sample_insufficient():
    result = portfolio_stats([_snap(0, 1000.0)], days=30)
    assert result["n_samples"] == 0
    assert result["insufficient_data"] is True


def test_portfolio_stats_flags_insufficient_below_threshold():
    # 13 days of data → 12 returns → insufficient
    snaps = [_snap(i, 1000.0 + i) for i in range(13)]
    result = portfolio_stats(snaps, days=30)
    assert result["insufficient_data"] is True
    assert result["sharpe"] is None  # not annualised yet


def test_portfolio_stats_annualises_with_enough_samples():
    # 20 days of monotonically rising values → strong Sharpe, no drawdown
    snaps = [_snap(i, 1000.0 + (19 - i) * 5) for i in range(20)]
    result = portfolio_stats(snaps, days=30)
    assert result["insufficient_data"] is False
    assert result["sharpe"] is not None
    assert result["sortino"] is None  # no negative returns → no downside std
    assert result["max_drawdown_pct"] == 0.0
    assert result["n_samples"] >= MIN_SAMPLES_FOR_ANNUALISATION


def test_portfolio_stats_handles_monotonic_negative():
    # Steady decline → sortino well-defined, max_drawdown > 0
    snaps = [_snap(i, 1000.0 - (19 - i) * 5) for i in range(20)]
    result = portfolio_stats(snaps, days=30)
    assert result["insufficient_data"] is False
    assert result["sharpe"] is not None
    assert result["sortino"] is not None
    assert result["max_drawdown_pct"] > 0.0


def test_portfolio_stats_resamples_intraday_to_last_of_day():
    # Two snapshots on the same day: keep only the last one.
    day0 = _T0 - timedelta(days=2)
    day1 = _T0 - timedelta(days=1)
    snaps = [
        FakeSnapshot(total_usd=1000.0, snapshot_at=day0),
        FakeSnapshot(total_usd=1005.0, snapshot_at=day0 + timedelta(hours=6)),
        FakeSnapshot(total_usd=1010.0, snapshot_at=day0 + timedelta(hours=23)),
        FakeSnapshot(total_usd=1020.0, snapshot_at=day1),
    ]
    result = portfolio_stats(snaps, days=30)
    # Two days → one return → sharpe/sortino stay None but function survives
    assert result["n_samples"] == 1
    assert result["max_drawdown_pct"] == 0.0


def test_portfolio_stats_zero_value_snapshot_ignored():
    # A zero (or negative) equity value cannot produce a % return.
    snaps = [
        _snap(2, 0.0),
        _snap(1, 1000.0),
        _snap(0, 1100.0),
    ]
    result = portfolio_stats(snaps, days=30)
    # Only 1 usable return (from day1 to day0). Should not crash.
    assert result["n_samples"] == 1
