import asyncio
import ccxt.async_support as ccxt
import logging
from bot.exchange.schemas import Ticker, Balance, OrderRequest, OrderResult

logger = logging.getLogger(__name__)


class CoinbaseClient:
    def __init__(self, api_key: str, api_secret: str):
        # Normalize PEM private keys: convert literal \n to real newlines
        normalized_secret = api_secret.replace("\\n", "\n").strip()

        self._exchange = ccxt.coinbase({
            "apiKey": api_key.strip(),
            "secret": normalized_secret,
            "enableRateLimit": True,
            "options": {
                # Market BUYs on Coinbase: pass the USD cost as the `amount` argument.
                # This lets us do "spend exactly $5" instead of "buy exactly 0.0021 ETH".
                "createMarketBuyOrderRequiresPrice": False,
            },
        })
        self._semaphore = asyncio.Semaphore(10)

    async def close(self):
        await self._exchange.close()

    async def _throttled(self, coro):
        async with self._semaphore:
            return await coro

    async def fetch_ticker(self, symbol: str) -> Ticker:
        data = await self._throttled(self._exchange.fetch_ticker(symbol))
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
        data = await self._throttled(self._exchange.fetch_balance())
        balances = []
        for currency, info in data.get("total", {}).items():
            if info and info > 0:
                balances.append(Balance(
                    currency=currency,
                    free=data["free"].get(currency, 0) or 0,
                    used=data["used"].get(currency, 0) or 0,
                    total=info,
                ))
        return balances

    async def create_order(self, req: OrderRequest) -> OrderResult:
        if req.order_type == "market":
            if req.side == "buy":
                # Coinbase quirk: market buys need the USD cost, not the crypto amount
                cost_usd = req.cost
                if not cost_usd or cost_usd <= 0:
                    # Calculate from current price if not provided
                    ticker = await self._exchange.fetch_ticker(req.symbol)
                    cost_usd = ticker["last"] * req.amount
                logger.info(f"Coinbase market BUY: spending ${cost_usd:.4f} on {req.symbol}")
                order = await self._throttled(
                    self._exchange.create_market_buy_order(req.symbol, cost_usd)
                )
            else:
                # Market sell: pass the crypto amount to receive USD
                order = await self._throttled(
                    self._exchange.create_market_sell_order(req.symbol, req.amount)
                )
        else:
            order = await self._throttled(
                self._exchange.create_limit_order(req.symbol, req.side, req.amount, req.price)
            )

        # Parse result defensively (Coinbase sometimes returns incomplete data)
        filled_amount = float(order.get("filled") or order.get("amount") or req.amount or 0)
        price = float(order.get("average") or order.get("price") or req.price or 0)
        cost = float(order.get("cost") or (price * filled_amount if price else (req.cost or 0)) or 0)

        # Derive missing fields
        if not price and cost and filled_amount:
            price = cost / filled_amount
        if not filled_amount and cost and price:
            filled_amount = cost / price

        fee_val = 0.0
        fee = order.get("fee") or {}
        if isinstance(fee, dict) and fee.get("cost"):
            try:
                fee_val = float(fee["cost"])
            except (ValueError, TypeError):
                pass

        status = order.get("status") or "filled"
        order_id = str(order.get("id") or "")

        logger.info(f"Order executed: {req.side} {filled_amount} {req.symbol} @ {price} (cost ${cost:.4f})")
        return OrderResult(
            order_id=order_id,
            symbol=req.symbol,
            side=req.side,
            order_type=req.order_type,
            amount=filled_amount,
            price=price,
            cost=cost,
            fee=fee_val,
            status=status,
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            await self._throttled(self._exchange.cancel_order(order_id, symbol))
            return True
        except Exception as e:
            logger.error(f"Failed to cancel order {order_id}: {e}")
            return False

    async def fetch_my_trades(self, symbol: str | None = None, since: int | None = None, limit: int = 100) -> list[dict]:
        """Fetch user's own executed trades from Coinbase."""
        try:
            if symbol:
                trades = await self._throttled(
                    self._exchange.fetch_my_trades(symbol, since=since, limit=limit)
                )
            else:
                trades = await self._throttled(
                    self._exchange.fetch_my_trades(since=since, limit=limit)
                )
            return trades or []
        except Exception as e:
            logger.warning(f"fetch_my_trades({symbol}) failed: {e}")
            return []

    async def fetch_closed_orders(self, symbol: str | None = None, since: int | None = None, limit: int = 100) -> list[dict]:
        """Fetch user's closed (filled/cancelled) orders from Coinbase."""
        try:
            if symbol:
                orders = await self._throttled(
                    self._exchange.fetch_closed_orders(symbol, since=since, limit=limit)
                )
            else:
                orders = await self._throttled(
                    self._exchange.fetch_closed_orders(since=since, limit=limit)
                )
            return orders or []
        except Exception as e:
            logger.warning(f"fetch_closed_orders({symbol}) failed: {e}")
            return []

    async def fetch_open_orders(self, symbol: str | None = None) -> list[dict]:
        try:
            if symbol:
                return await self._throttled(self._exchange.fetch_open_orders(symbol)) or []
            return await self._throttled(self._exchange.fetch_open_orders()) or []
        except Exception as e:
            logger.warning(f"fetch_open_orders failed: {e}")
            return []

    async def fetch_detailed_balance(self) -> dict:
        """Returns full balance info including free/used/total per currency."""
        try:
            data = await self._throttled(self._exchange.fetch_balance())
            currencies = {}
            for currency in data.get("total", {}):
                total = data["total"].get(currency) or 0
                if total > 0 or currency in ("USD", "USDC", "EUR"):
                    currencies[currency] = {
                        "free": float(data.get("free", {}).get(currency) or 0),
                        "used": float(data.get("used", {}).get(currency) or 0),
                        "total": float(total),
                    }
            return currencies
        except Exception as e:
            logger.error(f"fetch_detailed_balance failed: {e}")
            return {}

    async def validate_keys(self) -> dict:
        """Test connectivity and return balance summary."""
        try:
            balances = await self.fetch_balance()
            return {"valid": True, "balances": {b.currency: b.total for b in balances}}
        except ccxt.AuthenticationError as e:
            return {
                "valid": False,
                "error": (
                    "Invalid API key or secret. Para Coinbase Advanced/CDP: "
                    "el secret debe ser la EC Private Key COMPLETA en formato PEM "
                    "(con BEGIN/END y saltos de linea). Detalle: " + str(e)[:200]
                ),
            }
        except ccxt.PermissionDenied as e:
            return {"valid": False, "error": f"Key necesita permiso 'Trade'. Detalle: {str(e)[:200]}"}
        except Exception as e:
            return {"valid": False, "error": f"Error: {type(e).__name__}: {str(e)[:300]}"}
