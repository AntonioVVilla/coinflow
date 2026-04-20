"""Risk management: pre-trade checks, daily loss limits, circuit breakers."""
import logging
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from bot.database import async_session
from bot.models import RiskConfig, PortfolioSnapshot
from bot.engine.runner import get_exchange_client
from bot.config import settings

logger = logging.getLogger(__name__)


async def get_risk_config() -> RiskConfig | None:
    async with async_session() as session:
        result = await session.execute(select(RiskConfig).limit(1))
        return result.scalar_one_or_none()


async def check_pre_trade(strategy: str, side: str, symbol: str, cost_usd: float) -> tuple[bool, str]:
    """Returns (allowed, reason). Called before each order."""
    config = await get_risk_config()
    if not config or not config.enabled:
        return True, ""

    now = datetime.now(timezone.utc)

    # Paused by circuit breaker
    if config.paused_until and config.paused_until > now:
        remaining = int((config.paused_until - now).total_seconds() / 60)
        return False, f"Trading pausado por circuit breaker ({remaining}min restantes)"

    client = get_exchange_client()
    if not client:
        return True, ""

    # Get current portfolio value
    try:
        balances = await client.fetch_balance()
        balance_map = {b.currency: b.total for b in balances}

        prices = {}
        for sym in settings.supported_symbols:
            try:
                ticker = await client.fetch_ticker(sym)
                prices[sym] = ticker.last
            except Exception as ticker_err:
                logger.debug(f"Ticker fetch failed for {sym}: {ticker_err}")

        total_usd = balance_map.get("USD", 0) or 0
        btc_value = (balance_map.get("BTC", 0) or 0) * prices.get("BTC/USD", 0)
        eth_value = (balance_map.get("ETH", 0) or 0) * prices.get("ETH/USD", 0)
        total_usd += btc_value + eth_value

        if total_usd <= 0:
            return True, ""

        # Daily loss limit
        if config.max_daily_loss_usd > 0 and config.daily_reference_usd > 0:
            # Reset reference if new day
            if config.daily_reference_at is None or \
               config.daily_reference_at.date() < now.date():
                async with async_session() as session:
                    ref_result = await session.execute(select(RiskConfig).limit(1))
                    rc = ref_result.scalar_one_or_none()
                    if rc:
                        rc.daily_reference_usd = total_usd
                        rc.daily_reference_at = now
                        await session.commit()
            else:
                loss = config.daily_reference_usd - total_usd
                if loss >= config.max_daily_loss_usd:
                    return False, f"Limite de perdida diaria alcanzado: -${loss:.2f}"

        # Max drawdown (vs peak in last 30 days)
        if config.max_drawdown_pct > 0:
            since = now - timedelta(days=30)
            async with async_session() as session:
                peak_result = await session.execute(
                    select(func.max(PortfolioSnapshot.total_usd))
                    .where(PortfolioSnapshot.snapshot_at >= since)
                )
                peak_value = peak_result.scalar()
                peak: float = float(peak_value) if peak_value is not None else total_usd
                if peak > 0:
                    dd = (peak - total_usd) / peak * 100
                    if dd >= config.max_drawdown_pct:
                        return False, f"Drawdown maximo excedido: -{dd:.1f}% desde peak de ${peak:.2f}"

        # Max allocation per asset (only check on BUYs)
        if side == "buy":
            if symbol == "BTC/USD" and config.max_btc_allocation_pct < 100:
                future_btc_value = btc_value + cost_usd
                future_pct = future_btc_value / (total_usd + 0.0001) * 100
                if future_pct > config.max_btc_allocation_pct:
                    return False, f"Excede max exposicion BTC ({future_pct:.1f}% > {config.max_btc_allocation_pct}%)"

            if symbol == "ETH/USD" and config.max_eth_allocation_pct < 100:
                future_eth_value = eth_value + cost_usd
                future_pct = future_eth_value / (total_usd + 0.0001) * 100
                if future_pct > config.max_eth_allocation_pct:
                    return False, f"Excede max exposicion ETH ({future_pct:.1f}% > {config.max_eth_allocation_pct}%)"

    except Exception as e:
        logger.error(f"Risk check error: {e}")

    return True, ""


async def check_circuit_breaker():
    """Called periodically. Detects rapid market drops and pauses trading."""
    config = await get_risk_config()
    if not config or not config.enabled or config.circuit_breaker_pct <= 0:
        return

    client = get_exchange_client()
    if not client:
        return

    # Check if price dropped more than X% in last hour for either asset
    try:
        for symbol in settings.supported_symbols:
            ohlcv = await client._exchange.fetch_ohlcv(symbol, "5m", limit=13)
            if len(ohlcv) < 2:
                continue
            oldest = ohlcv[0][4]  # close price 1h ago
            latest = ohlcv[-1][4]
            drop_pct = (oldest - latest) / oldest * 100
            if drop_pct >= config.circuit_breaker_pct:
                pause_until = datetime.now(timezone.utc) + timedelta(hours=1)
                async with async_session() as session:
                    result = await session.execute(select(RiskConfig).limit(1))
                    rc = result.scalar_one_or_none()
                    if rc:
                        rc.paused_until = pause_until
                        await session.commit()
                logger.warning(
                    f"CIRCUIT BREAKER TRIGGERED: {symbol} cayo {drop_pct:.2f}% en 1h. "
                    f"Trading pausado 1 hora."
                )
                return
    except Exception as e:
        logger.error(f"Circuit breaker check error: {e}")
