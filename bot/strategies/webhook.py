import logging
from bot.strategies.base import BaseStrategy
from bot.exchange.schemas import Ticker, OrderRequest

logger = logging.getLogger(__name__)


class WebhookStrategy(BaseStrategy):
    """Executes trades from TradingView webhook alerts. Event-driven, not tick-based."""
    name = "webhook"

    def __init__(self):
        self.passphrase: str = ""
        self.default_amount_usd: float = 100
        self.symbol: str = "BTC/USD"
        self.signals_received: int = 0

    async def setup(self, params: dict) -> None:
        self.passphrase = params.get("passphrase", "")
        self.default_amount_usd = params.get("default_amount_usd", 100)
        self.symbol = params.get("symbol", "BTC/USD")
        logger.info(f"Webhook strategy ready for {self.symbol}")

    async def tick(self, ticker: Ticker) -> list[OrderRequest]:
        # Webhook strategy is event-driven, tick does nothing
        return []

    async def teardown(self) -> None:
        logger.info(f"Webhook strategy stopped. {self.signals_received} signals processed.")

    def execute_signal(self, signal: dict, current_price: float) -> OrderRequest | None:
        """Process a TradingView webhook signal."""
        passphrase = signal.get("passphrase", "")
        if self.passphrase and passphrase != self.passphrase:
            logger.warning("Webhook signal rejected: invalid passphrase")
            return None

        action = signal.get("action", "").lower()
        if action not in ("buy", "sell"):
            logger.warning(f"Webhook signal rejected: invalid action '{action}'")
            return None

        symbol = signal.get("symbol", self.symbol)
        amount_usd = float(signal.get("amount_usd", self.default_amount_usd))
        amount = amount_usd / current_price if action == "buy" else float(signal.get("amount", amount_usd / current_price))

        self.signals_received += 1
        logger.info(f"Webhook signal: {action} {amount:.8f} {symbol} (signal #{self.signals_received})")

        # For market buys, pass USD cost for Coinbase compatibility
        cost = amount_usd if action == "buy" else None
        return OrderRequest(
            symbol=symbol,
            side=action,
            order_type="market",
            amount=amount,
            cost=cost,
        )

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "default_amount_usd": self.default_amount_usd,
            "signals_received": self.signals_received,
        }
