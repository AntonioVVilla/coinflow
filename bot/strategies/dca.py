import asyncio
import logging
from sqlalchemy import select, func
from bot.strategies.base import BaseStrategy
from bot.exchange.schemas import Ticker, OrderRequest
from bot.database import async_session
from bot.log_utils import safe
from bot.models import Trade

logger = logging.getLogger(__name__)


class DCAStrategy(BaseStrategy):
    name = "dca"

    def __init__(self):
        self.amount_usd: float = 0
        self.symbol: str = "BTC/USD"
        self.total_invested: float = 0
        self.total_bought: float = 0
        self.num_buys: int = 0
        self.last_error: str = ""
        self._lock = asyncio.Lock()  # Prevents concurrent tick execution

    async def setup(self, params: dict) -> None:
        self.amount_usd = params["amount_usd"]
        self.symbol = params.get("symbol", "BTC/USD")

        # Load historical counters from the trades table
        await self._reload_counters()

        logger.info(
            f"DCA setup: {self.symbol}, ${self.amount_usd} per interval. "
            f"Restored {self.num_buys} past buys, ${self.total_invested:.2f} invested."
        )

    async def _reload_counters(self) -> None:
        """Recompute counters from the Trade table so they survive restarts."""
        async with async_session() as session:
            result = await session.execute(
                select(
                    func.count(Trade.id),
                    func.sum(Trade.cost),
                    func.sum(Trade.amount),
                ).where(
                    Trade.strategy == "dca",
                    Trade.side == "buy",
                    Trade.symbol == self.symbol,
                )
            )
            count, cost, amount = result.one()
            self.num_buys = count or 0
            self.total_invested = float(cost or 0)
            self.total_bought = float(amount or 0)

    async def tick(self, ticker: Ticker) -> list[OrderRequest]:
        """Decides to buy. Counters are updated externally only on success."""
        async with self._lock:
            price = ticker.last
            if price <= 0:
                return []
            amount = self.amount_usd / price
            logger.info(
                "DCA tick: intent to spend $%.2f on %s (~%.8f @ $%.2f)",
                self.amount_usd, safe(self.symbol), amount, price,
            )
            return [OrderRequest(
                symbol=self.symbol,
                side="buy",
                order_type="market",
                amount=amount,
                cost=self.amount_usd,
            )]

    async def on_trade_executed(self, result) -> None:
        """Called by the runner after a successful trade."""
        # Reload from DB to stay in sync (accounts for concurrent updates)
        await self._reload_counters()
        self.last_error = ""
        avg = self.total_invested / self.total_bought if self.total_bought > 0 else 0
        logger.info(
            f"DCA buy #{self.num_buys} confirmed: {result.amount:.8f} @ ${result.price:.2f} "
            f"(avg: ${avg:.2f}, total invested: ${self.total_invested:.2f})"
        )

    async def on_trade_failed(self, request, error: str) -> None:
        """Called by the runner after a failed trade."""
        self.last_error = error
        logger.warning(f"DCA trade failed: {error}")

    async def teardown(self) -> None:
        logger.info(
            f"DCA stopped. Total: ${self.total_invested:.2f} invested, "
            f"{self.total_bought:.8f} bought over {self.num_buys} buys"
        )

    def get_status(self) -> dict:
        avg_price = self.total_invested / self.total_bought if self.total_bought > 0 else 0
        status = {
            "name": self.name,
            "amount_usd": self.amount_usd,
            "total_invested": round(self.total_invested, 2),
            "total_bought": round(self.total_bought, 8),
            "num_buys": self.num_buys,
            "avg_price": round(avg_price, 2),
        }
        if self.last_error:
            status["last_error"] = self.last_error[:120]
        return status
