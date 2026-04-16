from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession
from bot.web.deps import get_db
from bot.models import Trade, PortfolioSnapshot
from bot.engine.runner import get_exchange_client, get_all_statuses
from bot.exchange.forex import get_usd_to_eur
from bot.config import settings

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("")
async def get_dashboard(db: AsyncSession = Depends(get_db)):
    client = get_exchange_client()

    # Current balances
    balances = {}
    if client:
        try:
            raw = await client.fetch_balance()
            balances = {b.currency: {"free": b.free, "total": b.total} for b in raw}
        except Exception:
            pass

    # Current prices
    prices = {}
    if client:
        for symbol in settings.supported_symbols:
            try:
                ticker = await client.fetch_ticker(symbol)
                prices[symbol] = ticker.last
            except Exception:
                pass

    # Get USD/EUR rate for EUR -> USD conversion
    eur_rate = await get_usd_to_eur()
    usd_per_eur = (1 / eur_rate) if eur_rate else 1.18

    # Calculate USD value of each asset (each counted ONCE)
    asset_usd = {}  # currency -> USD equivalent
    for currency, info in balances.items():
        amt = info.get("total", 0) or 0
        if amt <= 0:
            continue
        if currency == "USD":
            asset_usd[currency] = amt
        elif currency == "USDC":
            asset_usd[currency] = amt  # 1:1 peg
        elif currency == "EUR":
            asset_usd[currency] = amt * usd_per_eur
        else:
            # Crypto: use /USD pair first, fall back to /USDC, then /EUR
            val_usd = 0
            for quote in ("USD", "USDC"):
                sym = f"{currency}/{quote}"
                if sym in prices:
                    val_usd = amt * prices[sym]
                    break
            if not val_usd:
                sym_eur = f"{currency}/EUR"
                if sym_eur in prices:
                    val_usd = amt * prices[sym_eur] * usd_per_eur
            if val_usd:
                asset_usd[currency] = val_usd

    total_usd = sum(asset_usd.values())

    # Recent trades
    result = await db.execute(
        select(Trade).order_by(desc(Trade.created_at)).limit(10)
    )
    recent_trades = result.scalars().all()

    # Trade stats
    result = await db.execute(
        select(
            func.count(Trade.id),
            func.sum(Trade.cost),
        ).where(Trade.side == "buy")
    )
    row = result.one()
    total_buys = row[0] or 0
    total_invested = row[1] or 0

    result = await db.execute(
        select(func.sum(Trade.cost)).where(Trade.side == "sell")
    )
    total_sold = result.scalar() or 0

    # Strategy statuses
    strategies = get_all_statuses()

    # Asset allocation: one entry per unique asset
    allocation = [
        {"label": currency, "value": round(usd_val, 2)}
        for currency, usd_val in sorted(asset_usd.items(), key=lambda kv: -kv[1])
    ]

    # USD -> EUR conversion rate
    eur_rate = await get_usd_to_eur()

    return {
        "balances": balances,
        "prices": prices,
        "total_usd": round(total_usd, 2),
        "total_eur": round(total_usd * eur_rate, 2),
        "eur_rate": eur_rate,
        "paper_mode": settings.paper_mode,
        "strategies": strategies,
        "allocation": allocation,
        "stats": {
            "total_buys": total_buys,
            "total_invested": round(total_invested, 2),
            "total_sold": round(total_sold, 2),
            "realized_pnl": round(total_sold - total_invested, 2),
        },
        "recent_trades": [
            {
                "id": t.id,
                "strategy": t.strategy,
                "symbol": t.symbol,
                "side": t.side,
                "amount": t.amount,
                "price": t.price,
                "cost": round(t.cost, 2),
                "is_paper": t.is_paper,
                "created_at": t.created_at.isoformat(),
            }
            for t in recent_trades
        ],
    }


@router.get("/diagnostic")
async def diagnostic():
    """Run account diagnostics: check balances, available pairs, permissions."""
    client = get_exchange_client()
    if not client:
        return {"ok": False, "error": "Exchange no inicializado"}

    report = {"ok": True, "paper_mode": settings.paper_mode, "checks": []}

    # 1. Fetch balances
    try:
        balances = await client.fetch_balance()
        bal_map = {b.currency: b.total for b in balances if b.total and b.total > 0}
        report["balances"] = bal_map
        report["checks"].append({
            "name": "Conexion API",
            "ok": True,
            "detail": f"{len(bal_map)} activos con saldo",
        })
    except Exception as e:
        report["checks"].append({
            "name": "Conexion API",
            "ok": False,
            "detail": str(e)[:200],
        })
        return report

    # 2. Check which quote currencies have accounts
    has_usd = "USD" in bal_map
    has_usdc = "USDC" in bal_map
    has_eur = "EUR" in bal_map
    report["checks"].append({
        "name": "Cuenta USD",
        "ok": has_usd,
        "detail": f"${bal_map.get('USD', 0):.2f}" if has_usd else "No tienes cuenta USD.",
    })
    report["checks"].append({
        "name": "Cuenta USDC",
        "ok": has_usdc,
        "detail": f"{bal_map.get('USDC', 0):.4f} USDC" if has_usdc else "No tienes USDC.",
    })
    report["checks"].append({
        "name": "Cuenta EUR",
        "ok": has_eur,
        "detail": f"€{bal_map.get('EUR', 0):.2f}" if has_eur else "No tienes cuenta EUR.",
    })

    # 3. Test price fetch for each pair
    pair_checks = []
    for sym in settings.supported_symbols:
        try:
            ticker = await client.fetch_ticker(sym)
            pair_checks.append({
                "symbol": sym,
                "ok": True,
                "price": round(ticker.last, 2),
                "tradeable": True,
            })
        except Exception as e:
            pair_checks.append({
                "symbol": sym,
                "ok": False,
                "error": str(e)[:150],
            })
    report["pairs"] = pair_checks

    # 4. Recommendations based on available quote balances
    recommendations = []
    if has_eur:
        recommendations.append(
            f"✅ Tienes €{bal_map.get('EUR', 0):.2f} en EUR. Usa pares BTC/EUR o ETH/EUR en DCA/Grid."
        )
    if has_usdc:
        recommendations.append(
            f"✅ Tienes {bal_map.get('USDC', 0):.2f} USDC. Usa pares BTC/USDC o ETH/USDC."
        )
    if has_usd:
        recommendations.append(
            f"✅ Tienes ${bal_map.get('USD', 0):.2f}. Usa pares BTC/USD o ETH/USD."
        )
    if not (has_eur or has_usd or has_usdc):
        recommendations.append(
            "⚠ No tienes saldo en EUR/USD/USDC. Para comprar crypto necesitas alguna de estas monedas primero. "
            "Si ya tienes crypto (ETH/BTC), puedes venderlo en Coinbase."
        )
    # Check if user has a crypto account that could be used for sells
    for asset in ("BTC", "ETH"):
        if asset in bal_map and bal_map[asset] > 0:
            recommendations.append(
                f"ℹ️ Tienes {bal_map[asset]:.8f} {asset} - puedes vender con market sell si lo necesitas."
            )

    report["recommendations"] = recommendations
    return report


@router.get("/forex")
async def forex_rate():
    """Get current USD->EUR rate."""
    rate = await get_usd_to_eur()
    return {"usd_to_eur": rate, "eur_to_usd": round(1 / rate, 6)}


@router.get("/portfolio-history")
async def portfolio_history(
    hours: int = Query(24, ge=0, le=8760),
    db: AsyncSession = Depends(get_db),
):
    """Portfolio value over time. hours=0 returns all history. Filters by current mode."""
    query = (
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.is_paper == settings.paper_mode)
        .order_by(PortfolioSnapshot.snapshot_at.asc())
    )
    if hours > 0:
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        query = query.where(PortfolioSnapshot.snapshot_at >= since)
    result = await db.execute(query)
    snapshots = result.scalars().all()
    return {
        "data": [
            {
                "t": s.snapshot_at.isoformat(),
                "total": s.total_usd,
                "btc": s.btc_balance,
                "eth": s.eth_balance,
                "usd": s.usd_balance,
            }
            for s in snapshots
        ]
    }


@router.get("/price-history")
async def price_history(
    symbol: str = "BTC/USD",
    timeframe: str = "1h",
    limit: int = Query(50, ge=10, le=300),
):
    """OHLCV candlestick data from the exchange."""
    client = get_exchange_client()
    if not client:
        return {"data": []}

    try:
        # Use the underlying ccxt exchange directly
        if hasattr(client, "_exchange"):
            ohlcv = await client._exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            return {
                "symbol": symbol,
                "timeframe": timeframe,
                "data": [
                    {"t": int(c[0]), "o": c[1], "h": c[2], "l": c[3], "c": c[4], "v": c[5]}
                    for c in ohlcv
                ],
            }
    except Exception as e:
        return {"data": [], "error": str(e)}
    return {"data": []}
