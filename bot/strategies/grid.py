import logging
from sqlalchemy import select, func
from bot.strategies.base import BaseStrategy
from bot.exchange.schemas import Ticker, OrderRequest
from bot.database import async_session
from bot.models import Trade

logger = logging.getLogger(__name__)


class GridStrategy(BaseStrategy):
    name = "grid"

    def __init__(self):
        self.lower_price: float = 0
        self.upper_price: float = 0
        self.num_grids: int = 0
        self.amount_per_grid: float = 0
        self.symbol: str = "BTC/USD"
        self.grid_levels: list[float] = []
        self.last_price: float | None = None
        self.active_orders: dict[float, str] = {}  # level -> side
        self.total_trades: int = 0
        self.total_bought_usd: float = 0
        self.total_sold_usd: float = 0

    async def setup(self, params: dict) -> None:
        self.lower_price = params["lower_price"]
        self.upper_price = params["upper_price"]
        self.num_grids = params.get("num_grids", 10)
        self.amount_per_grid = params.get("amount_per_grid", 0.001)
        self.symbol = params.get("symbol", "BTC/USD")

        step = (self.upper_price - self.lower_price) / self.num_grids
        self.grid_levels = [self.lower_price + step * i for i in range(self.num_grids + 1)]
        self.last_price = None
        self.active_orders = {}

        # Load trade counters from history for get_status display
        async with async_session() as session:
            result = await session.execute(
                select(
                    func.count(Trade.id),
                    func.sum(Trade.cost).filter(Trade.side == "buy"),
                    func.sum(Trade.cost).filter(Trade.side == "sell"),
                ).where(
                    Trade.strategy == "grid",
                    Trade.symbol == self.symbol,
                )
            )
            total, bought, sold = result.one()
            self.total_trades = total or 0
            self.total_bought_usd = float(bought or 0)
            self.total_sold_usd = float(sold or 0)

        logger.info(
            f"Grid setup: {self.symbol} [{self.lower_price} - {self.upper_price}], "
            f"{self.num_grids} grids, {self.amount_per_grid} per grid. "
            f"Historial: {self.total_trades} trades, comprado ${self.total_bought_usd:.2f}, "
            f"vendido ${self.total_sold_usd:.2f}"
        )

    async def tick(self, ticker: Ticker) -> list[OrderRequest]:
        price = ticker.last
        orders: list[OrderRequest] = []

        if price < self.lower_price or price > self.upper_price:
            self.last_price = price
            return orders

        if self.last_price is None:
            self.last_price = price
            return orders

        for level in self.grid_levels:
            # Price crossed a grid level downward -> buy
            if self.last_price > level >= price and level not in self.active_orders:
                orders.append(OrderRequest(
                    symbol=self.symbol,
                    side="buy",
                    order_type="market",
                    amount=self.amount_per_grid,
                    cost=self.amount_per_grid * price,  # USD cost for Coinbase
                ))
                self.active_orders[level] = "buy"
                logger.info("Grid BUY triggered at level %.2f", level)

            # Price crossed a grid level upward -> sell
            elif self.last_price < level <= price and level not in self.active_orders:
                orders.append(OrderRequest(
                    symbol=self.symbol,
                    side="sell",
                    order_type="market",
                    amount=self.amount_per_grid,
                ))
                self.active_orders[level] = "sell"
                logger.info("Grid SELL triggered at level %.2f", level)

        # Reset filled levels so they can trigger again
        levels_to_reset = []
        for level, side in self.active_orders.items():
            if side == "buy" and price > level:
                levels_to_reset.append(level)
            elif side == "sell" and price < level:
                levels_to_reset.append(level)
        for level in levels_to_reset:
            del self.active_orders[level]

        self.last_price = price
        return orders

    async def teardown(self) -> None:
        self.active_orders.clear()
        logger.info("Grid strategy stopped")

    def get_status(self) -> dict:
        return {
            "name": self.name,
            "lower_price": self.lower_price,
            "upper_price": self.upper_price,
            "num_grids": self.num_grids,
            "active_levels": len(self.active_orders),
            "last_price": self.last_price,
            "total_trades": getattr(self, "total_trades", 0),
            "total_bought_usd": round(getattr(self, "total_bought_usd", 0), 2),
            "total_sold_usd": round(getattr(self, "total_sold_usd", 0), 2),
        }
