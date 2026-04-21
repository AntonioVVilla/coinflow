"""Shared performance analytics for live portfolio + backtest.

Exposes two independent building blocks:

1. `realized_pnl_fifo(trades)` — matches sell orders against previous buys in
   FIFO order per `(strategy, symbol)`. Returns realized P&L net of fees on
   both legs plus an "unmatched" bucket for sells with no matching buy
   history (e.g. Grid running against a pre-existing BTC position, or a
   Webhook signal that sells without any recorded prior buy).
2. `portfolio_stats(snapshots, days)` — derives Sharpe, Sortino, and max
   drawdown from a daily-resampled equity curve. Flags `insufficient_data`
   when fewer than 14 daily samples are available so the UI can explain
   why the numbers are not shown.

Both functions are pure and synchronous; the FastAPI layer pulls the data
and does the aggregation. Tests in `tests/test_metrics.py`.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date as _date
from datetime import datetime, timezone
from typing import Sequence

# A single sell consumes buy-lots in FIFO order. Each open lot tracks its
# remaining base-currency quantity, the per-unit effective cost (price plus
# the prorated buy-side fee), and when it was opened.
@dataclass
class _Lot:
    amount: float
    effective_price: float  # price + fee per unit
    opened_at: datetime


# Result schema returned by realized_pnl_fifo. Using a dict instead of a
# dataclass for trivial JSON serialisation in the API layer.
def _empty_key_stats() -> dict:
    return {
        "realized_pnl": 0.0,
        "trades_matched": 0,
        "avg_hold_seconds": 0.0,
        "wins": 0,
        "losses": 0,
        "unmatched_sell_amount": 0.0,
    }


def realized_pnl_fifo(
    trades: Sequence,
    *,
    now: datetime | None = None,
) -> dict:
    """Match sells against prior buys FIFO, per `(strategy, symbol)`.

    `trades` is any iterable of objects with these attributes (the Trade
    ORM model qualifies): `strategy`, `symbol`, `side`, `amount`, `price`,
    `cost`, `fee`, `created_at`.

    Returned shape::

        {
          "by_key": {
            "dca|BTC/USD": {
              "realized_pnl": 12.34,       # USD, net of fees both legs
              "trades_matched": 7,          # number of sell orders fully or
                                            # partially matched
              "avg_hold_seconds": 172800.0, # weighted by matched qty
              "wins": 4, "losses": 3,       # at sell-event granularity
              "unmatched_sell_amount": 0.0, # sell qty with no buy cover
            },
            ...
          },
          "global": {...same shape, summed across keys...},
        }
    """
    if now is None:
        now = datetime.now(timezone.utc)

    # Keep trades in chronological order so FIFO works.
    ordered = sorted(trades, key=lambda t: t.created_at)

    open_lots: dict[tuple[str, str], deque[_Lot]] = defaultdict(deque)
    key_stats: dict[tuple[str, str], dict] = defaultdict(_empty_key_stats)
    hold_weighted_sum: dict[tuple[str, str], float] = defaultdict(float)
    matched_amount: dict[tuple[str, str], float] = defaultdict(float)

    for trade in ordered:
        if trade.amount <= 0 or trade.price <= 0:
            continue

        key = (trade.strategy, trade.symbol)
        per_unit_fee = (trade.fee or 0.0) / trade.amount

        if trade.side == "buy":
            open_lots[key].append(_Lot(
                amount=trade.amount,
                effective_price=trade.price + per_unit_fee,
                opened_at=trade.created_at,
            ))
            continue

        # Sell: consume lots FIFO. Sell fee also reduces realized_pnl.
        lots = open_lots[key]
        remaining = trade.amount
        realized = 0.0
        sell_price_net = trade.price - per_unit_fee  # USD per unit, net of sell fee
        stats = key_stats[key]

        while remaining > 0 and lots:
            lot = lots[0]
            matched_qty = min(remaining, lot.amount)
            realized += (sell_price_net - lot.effective_price) * matched_qty
            hold_seconds = (trade.created_at - lot.opened_at).total_seconds()
            hold_weighted_sum[key] += hold_seconds * matched_qty
            matched_amount[key] += matched_qty

            lot.amount -= matched_qty
            remaining -= matched_qty
            if lot.amount <= 1e-12:
                lots.popleft()

        if remaining > 0:
            # No buy cover. Recorded as unmatched so the UI can show it
            # separately instead of silently inflating P&L.
            stats["unmatched_sell_amount"] += remaining

        if trade.amount - remaining > 0:
            # At least part of this sell was matched → counts as a trade
            # event. Classify win/loss on net realized of this sell.
            stats["trades_matched"] += 1
            stats["realized_pnl"] += realized
            if realized > 0:
                stats["wins"] += 1
            elif realized < 0:
                stats["losses"] += 1
            # Zero → neither win nor loss (flat exit).

    # Finalise avg_hold_seconds (amount-weighted).
    for key, stats in key_stats.items():
        qty = matched_amount[key]
        stats["avg_hold_seconds"] = (
            hold_weighted_sum[key] / qty if qty > 0 else 0.0
        )

    # Also tally any unmatched sells where we never entered key_stats because
    # the sell(s) never matched against any buy.
    for key, lots in open_lots.items():
        # Lots left are unrealized longs — not reported here (that's equity
        # curve territory, handled by portfolio_stats).
        _ = lots

    by_key = {f"{strat}|{sym}": stats for (strat, sym), stats in key_stats.items()}

    global_stats = _empty_key_stats()
    for stats in key_stats.values():
        global_stats["realized_pnl"] += stats["realized_pnl"]
        global_stats["trades_matched"] += stats["trades_matched"]
        global_stats["wins"] += stats["wins"]
        global_stats["losses"] += stats["losses"]
        global_stats["unmatched_sell_amount"] += stats["unmatched_sell_amount"]
    total_matched = sum(matched_amount.values())
    global_stats["avg_hold_seconds"] = (
        sum(hold_weighted_sum.values()) / total_matched if total_matched > 0 else 0.0
    )

    return {"by_key": by_key, "global": global_stats}


# ---------------------------------------------------------------------------
# Portfolio equity metrics (Sharpe / Sortino / max drawdown)
# ---------------------------------------------------------------------------

# Daily resample + risk-adjusted returns. Tests cover the edge cases
# (gaps, monotonic series, single sample, zero downside variance).

MIN_SAMPLES_FOR_ANNUALISATION = 14
TRADING_DAYS = 365  # crypto trades 24/7; no weekend gap

def _resample_to_daily(snapshots: Sequence) -> list[tuple[datetime, float]]:
    """Keep only the last snapshot of each UTC day."""
    by_day: dict[_date, tuple[datetime, float]] = {}
    for s in sorted(snapshots, key=lambda s: s.snapshot_at):
        day = s.snapshot_at.date()
        by_day[day] = (s.snapshot_at, float(s.total_usd))
    return [by_day[d] for d in sorted(by_day.keys())]


def portfolio_stats(snapshots: Sequence, days: int = 30) -> dict:
    """Compute risk-adjusted stats from a series of PortfolioSnapshot rows.

    Args:
        snapshots: Iterable of objects with `.snapshot_at` and `.total_usd`.
        days: Lookback window used to produce the daily series.

    Returns::

        {
          "sharpe": 1.23 | None,
          "sortino": 2.10 | None,
          "max_drawdown_pct": 12.5,
          "n_samples": 7,
          "insufficient_data": True,
          "days": 30,
        }
    """
    daily = _resample_to_daily(snapshots)
    if days and len(daily) > days + 1:
        daily = daily[-(days + 1):]

    returns: list[float] = []
    for (_, prev_value), (_, cur_value) in zip(daily, daily[1:]):
        if prev_value <= 0:
            continue
        returns.append((cur_value - prev_value) / prev_value)

    # n_samples counts *usable* daily returns, so the UI can condition on it
    # (matches the behaviour of insufficient_data below).
    n_samples = len(returns)
    insufficient = n_samples < MIN_SAMPLES_FOR_ANNUALISATION

    if n_samples == 0:
        return {
            "sharpe": None,
            "sortino": None,
            "max_drawdown_pct": 0.0,
            "n_samples": 0,
            "insufficient_data": True,
            "days": days,
        }

    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / len(returns)
    std = math.sqrt(variance)

    downside = [r for r in returns if r < 0]
    down_variance = (
        sum(r ** 2 for r in downside) / len(downside) if downside else 0.0
    )
    down_std = math.sqrt(down_variance)

    sharpe: float | None
    sortino: float | None
    if std > 0 and not insufficient:
        sharpe = round((mean / std) * math.sqrt(TRADING_DAYS), 2)
    else:
        sharpe = None
    if down_std > 0 and not insufficient:
        sortino = round((mean / down_std) * math.sqrt(TRADING_DAYS), 2)
    else:
        sortino = None

    # Max drawdown from the daily equity curve.
    peak = daily[0][1]
    max_dd = 0.0
    for _, value in daily:
        if value > peak:
            peak = value
        if peak > 0:
            dd = (peak - value) / peak * 100
            if dd > max_dd:
                max_dd = dd

    return {
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown_pct": round(max_dd, 2),
        "n_samples": n_samples,
        "insufficient_data": insufficient,
        "days": days,
    }


__all__ = [
    "realized_pnl_fifo",
    "portfolio_stats",
    "MIN_SAMPLES_FOR_ANNUALISATION",
]
