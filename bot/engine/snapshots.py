import logging
from bot.database import async_session
from bot.models import PortfolioSnapshot
from bot.engine.runner import get_exchange_client
from bot.config import settings

logger = logging.getLogger(__name__)


async def take_snapshot():
    """Capture current portfolio value and save as snapshot."""
    client = get_exchange_client()
    if not client:
        return

    try:
        balances = await client.fetch_balance()
        balance_map = {b.currency: b.total for b in balances}

        prices = {}
        for symbol in settings.supported_symbols:
            try:
                ticker = await client.fetch_ticker(symbol)
                prices[symbol] = ticker.last
            except Exception:
                pass

        usd = balance_map.get("USD", 0) or 0
        btc = balance_map.get("BTC", 0) or 0
        eth = balance_map.get("ETH", 0) or 0

        total = usd
        if "BTC/USD" in prices:
            total += btc * prices["BTC/USD"]
        if "ETH/USD" in prices:
            total += eth * prices["ETH/USD"]

        async with async_session() as session:
            snap = PortfolioSnapshot(
                total_usd=round(total, 2),
                btc_balance=btc,
                eth_balance=eth,
                usd_balance=usd,
                is_paper=settings.paper_mode,
            )
            session.add(snap)
            await session.commit()

        logger.debug(f"Portfolio snapshot: ${total:.2f}")
    except Exception as e:
        logger.error(f"Snapshot failed: {e}")
