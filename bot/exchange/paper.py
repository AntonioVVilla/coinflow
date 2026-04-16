import uuid
import logging
import ccxt.async_support as ccxt
from bot.exchange.schemas import Ticker, Balance, OrderRequest, OrderResult

logger = logging.getLogger(__name__)


class PaperClient:
    """Simulates trading using real prices but virtual balances."""

    def __init__(self, initial_usd: float = 10000.0):
        self._balances = {"USD": initial_usd, "BTC": 0.0, "ETH": 0.0}
        self._exchange = ccxt.coinbase({"enableRateLimit": True})

    async def close(self):
        await self._exchange.close()

    async def fetch_ticker(self, symbol: str) -> Ticker:
        data = await self._exchange.fetch_ticker(symbol)
        return Ticker(
            symbol=data["symbol"],
            last=data["last"],
            bid=data["bid"] or data["last"],
            ask=data["ask"] or data["last"],
            high=data["high"] or data["last"],
            low=data["low"] or data["last"],
            timestamp=data["timestamp"] or 0,
        )

    async def fetch_balance(self) -> list[Balance]:
        return [
            Balance(currency=c, free=v, used=0, total=v)
            for c, v in self._balances.items()
            if v > 0
        ]

    async def create_order(self, req: OrderRequest) -> OrderResult:
        ticker = await self.fetch_ticker(req.symbol)
        price = ticker.last

        base, quote = req.symbol.split("/")
        fee_rate = 0.006  # 0.6% simulated fee
        cost = price * req.amount
        fee = cost * fee_rate

        if req.side == "buy":
            total_cost = cost + fee
            if self._balances.get(quote, 0) < total_cost:
                raise Exception(f"Insufficient {quote} balance: need {total_cost:.2f}, have {self._balances.get(quote, 0):.2f}")
            self._balances[quote] = self._balances.get(quote, 0) - total_cost
            self._balances[base] = self._balances.get(base, 0) + req.amount
        else:
            if self._balances.get(base, 0) < req.amount:
                raise Exception(f"Insufficient {base} balance: need {req.amount}, have {self._balances.get(base, 0)}")
            self._balances[base] = self._balances.get(base, 0) - req.amount
            self._balances[quote] = self._balances.get(quote, 0) + cost - fee

        logger.info(f"[PAPER] {req.side} {req.amount} {req.symbol} @ {price}")
        return OrderResult(
            order_id=f"paper-{uuid.uuid4().hex[:12]}",
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            amount=req.amount,
            price=price,
            cost=cost,
            fee=fee,
            status="filled",
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        logger.info(f"[PAPER] Cancelled order {order_id}")
        return True

    async def validate_keys(self) -> dict:
        return {"valid": True, "balances": dict(self._balances)}
