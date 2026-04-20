"""Coinbase integration endpoints: sync historical data, account details."""
import logging
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.web.deps import get_db
from bot.models import Trade
from bot.engine.runner import get_exchange_client
from bot.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/coinbase", tags=["coinbase"])


@router.get("/accounts")
async def accounts():
    """Detailed balance info: free, used, total per currency + USD equivalent."""
    client = get_exchange_client()
    if not client:
        return {"ok": False, "error": "Exchange no inicializado"}

    if not hasattr(client, "fetch_detailed_balance"):
        # Paper client fallback
        balances = await client.fetch_balance()
        return {
            "ok": True,
            "accounts": [
                {"currency": b.currency, "free": b.free, "used": b.used, "total": b.total, "usd_value": None}
                for b in balances
            ],
        }

    currencies = await client.fetch_detailed_balance()

    # Compute USD value for each
    from bot.exchange.forex import get_usd_to_eur
    eur_rate = await get_usd_to_eur()
    usd_per_eur = 1 / eur_rate if eur_rate else 1.18

    # Get prices
    prices = {}
    for sym in settings.supported_symbols:
        try:
            t = await client.fetch_ticker(sym)
            prices[sym] = t.last
        except Exception as ticker_err:
            logger.debug(f"Ticker fetch failed for {sym}: {ticker_err}")

    accounts = []
    total_usd = 0
    for currency, info in currencies.items():
        usd_value = None
        total = info["total"]
        if currency == "USD":
            usd_value = total
        elif currency == "USDC":
            usd_value = total
        elif currency == "EUR":
            usd_value = total * usd_per_eur
        else:
            for quote in ("USD", "USDC"):
                if f"{currency}/{quote}" in prices:
                    usd_value = total * prices[f"{currency}/{quote}"]
                    break
            if usd_value is None and f"{currency}/EUR" in prices:
                usd_value = total * prices[f"{currency}/EUR"] * usd_per_eur

        if usd_value:
            total_usd += usd_value

        accounts.append({
            "currency": currency,
            "free": round(info["free"], 8),
            "used": round(info["used"], 8),
            "total": round(total, 8),
            "usd_value": round(usd_value, 2) if usd_value is not None else None,
        })

    # Sort by USD value desc
    accounts.sort(key=lambda a: -(a.get("usd_value") or 0))
    return {"ok": True, "accounts": accounts, "total_usd": round(total_usd, 2)}


@router.get("/open-orders")
async def open_orders(symbol: str | None = None):
    """Live open orders on Coinbase (not just bot ones)."""
    client = get_exchange_client()
    if not client or not hasattr(client, "fetch_open_orders"):
        return {"ok": False, "error": "Solo disponible en modo LIVE"}

    orders = await client.fetch_open_orders(symbol)
    return {
        "ok": True,
        "orders": [
            {
                "id": o.get("id"),
                "symbol": o.get("symbol"),
                "side": o.get("side"),
                "type": o.get("type"),
                "price": o.get("price"),
                "amount": o.get("amount"),
                "filled": o.get("filled"),
                "remaining": o.get("remaining"),
                "status": o.get("status"),
                "timestamp": o.get("timestamp"),
                "datetime": o.get("datetime"),
            }
            for o in orders
        ],
    }


@router.post("/sync-trades")
async def sync_trades(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
):
    """Fetch recent trades from Coinbase and upsert into local DB.

    Useful to import trades executed before the bot was configured,
    or to recover trades where the bot failed to persist them.
    """
    client = get_exchange_client()
    if not client or not hasattr(client, "fetch_my_trades"):
        return {"ok": False, "error": "Solo disponible en modo LIVE"}

    since_ms = int((datetime.now(timezone.utc).timestamp() - days * 86400) * 1000)

    imported = 0
    duplicates = 0
    errors = 0
    per_symbol_stats = {}

    for symbol in settings.supported_symbols:
        trades = await client.fetch_my_trades(symbol, since=since_ms, limit=500)
        per_symbol_stats[symbol] = {"fetched": len(trades), "imported": 0, "duplicates": 0}

        for t in trades:
            try:
                order_id = str(t.get("order") or t.get("id") or "")
                if not order_id:
                    continue

                # Skip if already imported (by order_id)
                existing = await db.execute(
                    select(Trade).where(Trade.order_id == order_id)
                )
                if existing.scalar_one_or_none():
                    duplicates += 1
                    per_symbol_stats[symbol]["duplicates"] += 1
                    continue

                ts_ms = t.get("timestamp") or 0
                created_at = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc) if ts_ms else datetime.now(timezone.utc)

                fee_cost = 0.0
                fee = t.get("fee") or {}
                if isinstance(fee, dict) and fee.get("cost"):
                    try:
                        fee_cost = float(fee["cost"])
                    except (TypeError, ValueError):
                        logger.debug("Could not parse fee cost for synced trade")

                trade = Trade(
                    strategy="synced",
                    symbol=t.get("symbol") or symbol,
                    side=t.get("side") or "buy",
                    order_type=t.get("type") or "market",
                    amount=float(t.get("amount") or 0),
                    price=float(t.get("price") or 0),
                    cost=float(t.get("cost") or 0),
                    fee=fee_cost,
                    order_id=order_id,
                    is_paper=False,
                    status="filled",
                    created_at=created_at,
                )
                db.add(trade)
                imported += 1
                per_symbol_stats[symbol]["imported"] += 1
            except Exception as e:
                logger.warning(f"Trade import failed: {e}")
                errors += 1

    await db.commit()

    return {
        "ok": True,
        "days": days,
        "imported": imported,
        "duplicates_skipped": duplicates,
        "errors": errors,
        "per_symbol": per_symbol_stats,
    }
