"""Read-only performance metrics endpoint for the Dashboard.

Exposes GET /api/metrics/summary?days=N which aggregates:
  - FIFO realized P&L per (strategy, symbol) and globally.
  - Sharpe / Sortino / max drawdown from portfolio_snapshots.

The heavy lifting lives in `bot.engine.metrics` and is unit-tested there;
this layer only pulls rows from the DB and passes them through.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.engine.metrics import portfolio_stats, realized_pnl_fifo
from bot.models import PortfolioSnapshot, Trade
from bot.web.deps import get_db

router = APIRouter(prefix="/api/metrics", tags=["metrics"])


@router.get("/summary")
async def metrics_summary(
    db: AsyncSession = Depends(get_db),
    days: int = Query(30, ge=1, le=365),
):
    """Return realized P&L + portfolio risk-adjusted stats."""
    since = datetime.now(timezone.utc) - timedelta(days=days)

    trades_result = await db.execute(
        select(Trade).where(Trade.created_at >= since).order_by(Trade.created_at)
    )
    trades = list(trades_result.scalars().all())

    snap_result = await db.execute(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.snapshot_at >= since)
        .order_by(PortfolioSnapshot.snapshot_at)
    )
    snapshots = list(snap_result.scalars().all())

    pnl = realized_pnl_fifo(trades)
    stats = portfolio_stats(snapshots, days=days)

    return {
        "days": days,
        "portfolio": stats,
        "pnl": pnl,
    }
