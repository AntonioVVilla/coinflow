from abc import ABC, abstractmethod
from bot.exchange.schemas import Ticker, OrderRequest


class BaseStrategy(ABC):
    name: str = ""

    @abstractmethod
    async def setup(self, params: dict) -> None:
        """Initialize strategy with config params."""

    @abstractmethod
    async def tick(self, ticker: Ticker) -> list[OrderRequest]:
        """Process a price tick. Return orders to execute."""

    @abstractmethod
    async def teardown(self) -> None:
        """Clean up when strategy is stopped."""

    def get_status(self) -> dict:
        """Return strategy-specific status info for the dashboard."""
        return {"name": self.name}
