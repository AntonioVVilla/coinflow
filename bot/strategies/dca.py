import asyncio
import logging
import time

from sqlalchemy import select, func

from bot.database import async_session
from bot.exchange.schemas import OrderRequest, Ticker
from bot.log_utils import safe
from bot.models import Trade
from bot.strategies.base import BaseStrategy

logger = logging.getLogger(__name__)

# After a SL/TP sell is emitted we suppress re-evaluation for a few minutes,
# long enough for _reload_counters to pick up the sell row and for the
# ticker to move past the trigger.
_SL_TP_COOLDOWN_SECONDS = 300


class DCAStrategy(BaseStrategy):
    name = "dca"

    def __init__(self):
        self.amount_usd: float = 0
        self.symbol: str = "BTC/USD"
        self.total_invested: float = 0  # sum(cost) of buys only
        self.total_bought: float = 0  # sum(amount) of buys only
        self.total_sold: float = 0  # sum(amount) of sells (incl. SL/TP)
        self.num_buys: int = 0
        self.last_error: str = ""
        self.stop_loss_pct: float = 0.0
        self.take_profit_pct: float = 0.0
        self._sl_tp_cooldown_until: float = 0.0
        self._lock = asyncio.Lock()  # Prevents concurrent tick execution

    # ------------------------------------------------------------------
    # Derived state

    @property
    def avg_buy_price(self) -> float:
        return self.total_invested / self.total_bought if self.total_bought > 0 else 0.0

    @property
    def net_bought(self) -> float:
        return self.total_bought - self.total_sold

    # ------------------------------------------------------------------

    async def setup(self, params: dict) -> None:
        self.amount_usd = params["amount_usd"]
        self.symbol = params.get("symbol", "BTC/USD")
        # Accept SL/TP expressed in percent. 0 = disabled.
        self.stop_loss_pct = float(params.get("stop_loss_pct") or 0)
        self.take_profit_pct = float(params.get("take_profit_pct") or 0)

        await self._reload_counters()

        logger.info(
            "DCA setup: %s, $%.2f per interval (SL=%.2f%%, TP=%.2f%%). "
            "Restored %d past buys, $%.2f invested.",
            safe(self.symbol), self.amount_usd,
            self.stop_loss_pct, self.take_profit_pct,
            self.num_buys, self.total_invested,
        )

    async def _reload_counters(self) -> None:
        """Recompute counters from the Trade table so they survive restarts."""
        async with async_session() as session:
            buy_result = await session.execute(
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
            count, cost, amount = buy_result.one()
            self.num_buys = count or 0
            self.total_invested = float(cost or 0)
            self.total_bought = float(amount or 0)

            sell_result = await session.execute(
                select(func.sum(Trade.amount)).where(
                    Trade.strategy == "dca",
                    Trade.side == "sell",
                    Trade.symbol == self.symbol,
                )
            )
            self.total_sold = float(sell_result.scalar() or 0)

    # ------------------------------------------------------------------
    # SL/TP evaluation. Called by the runner BEFORE the regular tick so the
    # avg_buy_price is pre-tick (any buy in the same tick doesn't pollute
    # the trigger).

    def evaluate_sl_tp(self, ticker: Ticker) -> list[OrderRequest]:
        if self.stop_loss_pct <= 0 and self.take_profit_pct <= 0:
            return []
        if self.net_bought <= 1e-9:
            return []
        if time.time() < self._sl_tp_cooldown_until:
            return []
        if ticker.last <= 0 or self.avg_buy_price <= 0:
            return []

        pct_move = (ticker.last - self.avg_buy_price) / self.avg_buy_price * 100

        triggered: str | None = None
        if self.stop_loss_pct > 0 and pct_move <= -self.stop_loss_pct:
            triggered = "stop_loss"
        elif self.take_profit_pct > 0 and pct_move >= self.take_profit_pct:
            triggered = "take_profit"

        if triggered is None:
            return []

        self._sl_tp_cooldown_until = time.time() + _SL_TP_COOLDOWN_SECONDS
        logger.warning(
            "DCA %s triggered on %s: last=$%.2f avg=$%.2f move=%.2f%% → sell %.8f",
            triggered, safe(self.symbol), ticker.last, self.avg_buy_price,
            pct_move, self.net_bought,
        )
        return [OrderRequest(
            symbol=self.symbol,
            side="sell",
            order_type="market",
            amount=self.net_bought,
            cost=ticker.last * self.net_bought,
            metadata={"trigger": triggered, "avg_buy_price": self.avg_buy_price},
        )]

    # ------------------------------------------------------------------

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
        await self._reload_counters()
        self.last_error = ""
        logger.info(
            "DCA %s confirmed: %.8f @ $%.2f (avg: $%.2f, net bought: %.8f)",
            safe(result.side), result.amount, result.price,
            self.avg_buy_price, self.net_bought,
        )

    async def on_trade_failed(self, request, error: str) -> None:
        """Called by the runner after a failed trade."""
        self.last_error = error
        logger.warning("DCA trade failed: %s", safe(error))

    async def teardown(self) -> None:
        logger.info(
            "DCA stopped. Total: $%.2f invested, %.8f bought over %d buys",
            self.total_invested, self.total_bought, self.num_buys,
        )

    def get_status(self) -> dict:
        status = {
            "name": self.name,
            "amount_usd": self.amount_usd,
            "total_invested": round(self.total_invested, 2),
            "total_bought": round(self.total_bought, 8),
            "net_bought": round(self.net_bought, 8),
            "num_buys": self.num_buys,
            "avg_price": round(self.avg_buy_price, 2),
            "stop_loss_pct": self.stop_loss_pct,
            "take_profit_pct": self.take_profit_pct,
        }
        if self.last_error:
            status["last_error"] = self.last_error[:120]
        return status
