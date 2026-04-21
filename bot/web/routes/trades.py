import csv
import io
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select, desc, asc, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from bot.web.deps import get_db
from bot.models import Trade

router = APIRouter(prefix="/api/trades", tags=["trades"])

# Allow-list of sortable columns. Keeps the API safe from arbitrary column
# injection and gives the UI a fixed contract.
_SORTABLE_COLUMNS = {
    "created_at": Trade.created_at,
    "cost": Trade.cost,
    "strategy": Trade.strategy,
    "side": Trade.side,
    "symbol": Trade.symbol,
    "amount": Trade.amount,
    "price": Trade.price,
}


def _build_filters(strategy, symbol, side, since_hours):
    conds = []
    if strategy:
        conds.append(Trade.strategy == strategy)
    if symbol:
        conds.append(Trade.symbol == symbol)
    if side:
        conds.append(Trade.side == side)
    if since_hours:
        since = datetime.now(timezone.utc) - timedelta(hours=since_hours)
        conds.append(Trade.created_at >= since)
    return and_(*conds) if conds else None


def _order_clause(order_by: str, order_dir: str):
    col = _SORTABLE_COLUMNS.get(order_by, Trade.created_at)
    return asc(col) if order_dir == "asc" else desc(col)


@router.get("")
async def list_trades(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    strategy: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
    since_hours: int | None = None,
    order_by: str = Query("created_at", pattern="^(created_at|cost|strategy|side|symbol|amount|price)$"),
    order_dir: str = Query("desc", pattern="^(asc|desc)$"),
    db: AsyncSession = Depends(get_db),
):
    filters = _build_filters(strategy, symbol, side, since_hours)

    query = select(Trade)
    count_query = select(func.count(Trade.id))
    if filters is not None:
        query = query.where(filters)
        count_query = count_query.where(filters)

    total = (await db.execute(count_query)).scalar() or 0
    offset = (page - 1) * limit
    result = await db.execute(
        query.order_by(_order_clause(order_by, order_dir)).offset(offset).limit(limit)
    )
    trades = result.scalars().all()

    return {
        "trades": [
            {
                "id": t.id,
                "strategy": t.strategy,
                "symbol": t.symbol,
                "side": t.side,
                "order_type": t.order_type,
                "amount": t.amount,
                "price": t.price,
                "cost": round(t.cost, 2),
                "fee": round(t.fee, 4),
                "is_paper": t.is_paper,
                "status": t.status,
                "created_at": t.created_at.isoformat(),
            }
            for t in trades
        ],
        "total": total,
        "page": page,
        "pages": (total + limit - 1) // limit,
        "order_by": order_by,
        "order_dir": order_dir,
    }


@router.get("/stats")
async def trade_stats(
    since_hours: int = Query(168, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """Aggregate trade statistics for charts."""
    since = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    # Volume by strategy
    result = await db.execute(
        select(
            Trade.strategy,
            func.count(Trade.id),
            func.sum(Trade.cost),
            func.sum(Trade.fee),
        )
        .where(Trade.created_at >= since)
        .group_by(Trade.strategy)
    )
    by_strategy = [
        {"strategy": r[0], "trades": r[1], "volume": round(r[2] or 0, 2), "fees": round(r[3] or 0, 4)}
        for r in result.all()
    ]

    # Volume by side
    result = await db.execute(
        select(Trade.side, func.count(Trade.id), func.sum(Trade.cost))
        .where(Trade.created_at >= since)
        .group_by(Trade.side)
    )
    by_side = [{"side": r[0], "trades": r[1], "volume": round(r[2] or 0, 2)} for r in result.all()]

    # Volume by symbol
    result = await db.execute(
        select(Trade.symbol, func.count(Trade.id), func.sum(Trade.cost))
        .where(Trade.created_at >= since)
        .group_by(Trade.symbol)
    )
    by_symbol = [{"symbol": r[0], "trades": r[1], "volume": round(r[2] or 0, 2)} for r in result.all()]

    # Daily activity (count + volume per day)
    result = await db.execute(
        select(
            func.date(Trade.created_at),
            func.count(Trade.id),
            func.sum(Trade.cost),
        )
        .where(Trade.created_at >= since)
        .group_by(func.date(Trade.created_at))
        .order_by(func.date(Trade.created_at))
    )
    by_day = [{"date": str(r[0]), "trades": r[1], "volume": round(r[2] or 0, 2)} for r in result.all()]

    # Totals
    result = await db.execute(
        select(
            func.count(Trade.id),
            func.sum(Trade.cost),
            func.sum(Trade.fee),
        ).where(Trade.created_at >= since)
    )
    row = result.one()
    totals = {
        "total_trades": row[0] or 0,
        "total_volume": round(row[1] or 0, 2),
        "total_fees": round(row[2] or 0, 4),
    }

    return {
        "since_hours": since_hours,
        "totals": totals,
        "by_strategy": by_strategy,
        "by_side": by_side,
        "by_symbol": by_symbol,
        "by_day": by_day,
    }


@router.get("/export.csv")
async def export_csv(
    strategy: str | None = None,
    symbol: str | None = None,
    side: str | None = None,
    since_hours: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    filters = _build_filters(strategy, symbol, side, since_hours)
    query = select(Trade).order_by(desc(Trade.created_at))
    if filters is not None:
        query = query.where(filters)

    result = await db.execute(query)
    trades = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "created_at", "strategy", "symbol", "side", "order_type",
                     "amount", "price", "cost", "fee", "is_paper", "status", "order_id"])
    for t in trades:
        writer.writerow([
            t.id, t.created_at.isoformat(), t.strategy, t.symbol, t.side, t.order_type,
            t.amount, t.price, t.cost, t.fee, t.is_paper, t.status, t.order_id,
        ])
    buf.seek(0)

    filename = f"trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
