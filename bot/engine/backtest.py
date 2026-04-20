"""Backtest engine: replay a strategy over historical OHLCV data.

Fetches historical candles from Coinbase and simulates strategy ticks,
returning detailed metrics (P&L, # trades, max drawdown, win rate).
"""
import logging
from dataclasses import dataclass, field
from bot.exchange.schemas import Ticker
from bot.strategies.grid import GridStrategy
from bot.strategies.dca import DCAStrategy
from bot.engine.runner import get_exchange_client

logger = logging.getLogger(__name__)


@dataclass
class SimulatedPosition:
    """Virtual balance tracker during backtest."""
    quote_balance: float
    base_balance: float = 0.0
    fees_paid: float = 0.0
    fee_rate: float = 0.006  # 0.6% taker (Coinbase Advanced)
    peak_value: float = 0.0
    current_value: float = 0.0
    trades: list[dict] = field(default_factory=list)

    def execute(self, side: str, amount: float, price: float, ts: int) -> bool:
        """Execute a simulated order. Returns True on success."""
        cost = amount * price
        fee = cost * self.fee_rate

        if side == "buy":
            total = cost + fee
            if self.quote_balance < total:
                return False
            self.quote_balance -= total
            self.base_balance += amount
        else:
            if self.base_balance < amount:
                return False
            self.base_balance -= amount
            self.quote_balance += cost - fee

        self.fees_paid += fee
        self.trades.append({
            "ts": ts, "side": side, "amount": amount,
            "price": price, "cost": cost, "fee": fee,
        })
        return True

    def mark_to_market(self, price: float):
        self.current_value = self.quote_balance + self.base_balance * price
        if self.current_value > self.peak_value:
            self.peak_value = self.current_value


def _compute_metrics(position: SimulatedPosition, initial_value: float,
                     final_price: float, start_price: float) -> dict:
    final_value = position.quote_balance + position.base_balance * final_price
    total_return_pct = (final_value - initial_value) / initial_value * 100 if initial_value else 0

    # HODL comparison: if we had just held base asset
    hodl_amount = initial_value / start_price
    hodl_value = hodl_amount * final_price
    hodl_return_pct = (hodl_value - initial_value) / initial_value * 100 if initial_value else 0

    # Drawdown
    drawdown_pct = (position.peak_value - final_value) / position.peak_value * 100 if position.peak_value else 0

    # Win rate (pairs of buy-sell assumed sequential)
    buys = [t for t in position.trades if t["side"] == "buy"]
    sells = [t for t in position.trades if t["side"] == "sell"]
    wins = 0
    losses = 0
    for i, sell in enumerate(sells):
        if i < len(buys):
            if sell["price"] > buys[i]["price"]:
                wins += 1
            else:
                losses += 1

    return {
        "initial_value": round(initial_value, 2),
        "final_value": round(final_value, 2),
        "total_return_pct": round(total_return_pct, 2),
        "total_return_usd": round(final_value - initial_value, 2),
        "hodl_return_pct": round(hodl_return_pct, 2),
        "hodl_return_usd": round(hodl_value - initial_value, 2),
        "vs_hodl_pct": round(total_return_pct - hodl_return_pct, 2),
        "num_trades": len(position.trades),
        "num_buys": len(buys),
        "num_sells": len(sells),
        "total_fees": round(position.fees_paid, 4),
        "max_drawdown_pct": round(drawdown_pct, 2),
        "peak_value": round(position.peak_value, 2),
        "win_rate_pct": round((wins / (wins + losses) * 100) if (wins + losses) > 0 else 0, 2),
        "wins": wins,
        "losses": losses,
        "final_base_balance": round(position.base_balance, 8),
        "final_quote_balance": round(position.quote_balance, 2),
    }


async def run_backtest(
    strategy_name: str,
    symbol: str,
    params: dict,
    initial_quote: float = 1000.0,
    timeframe: str = "1h",
    candles: int = 500,
) -> dict:
    """Run a backtest of a strategy over historical candles.

    Returns metrics + full trade log.
    """
    client = get_exchange_client()
    if not client or not hasattr(client, "_exchange"):
        return {"ok": False, "error": "Exchange not available"}

    # Instantiate strategy without DB-backed setup (backtest is isolated)
    strategy: GridStrategy | DCAStrategy
    if strategy_name == "grid":
        strategy = GridStrategy()
    elif strategy_name == "dca":
        strategy = DCAStrategy()
    else:
        return {"ok": False, "error": f"Strategy '{strategy_name}' no soportada para backtest"}

    # Inject params directly (skip DB load)
    params_copy = dict(params)
    params_copy["symbol"] = symbol
    try:
        if isinstance(strategy, GridStrategy):
            strategy.lower_price = params["lower_price"]
            strategy.upper_price = params["upper_price"]
            strategy.num_grids = params.get("num_grids", 10)
            strategy.amount_per_grid = params.get("amount_per_grid", 0.001)
            strategy.symbol = symbol
            step = (strategy.upper_price - strategy.lower_price) / strategy.num_grids
            strategy.grid_levels = [strategy.lower_price + step * i for i in range(strategy.num_grids + 1)]
        elif isinstance(strategy, DCAStrategy):
            strategy.amount_usd = params["amount_usd"]
            strategy.symbol = symbol
    except KeyError as e:
        logger.warning("Backtest missing param: %s", e)
        return {"ok": False, "error": "Falta un parametro obligatorio"}

    # Fetch historical candles
    try:
        ohlcv = await client._exchange.fetch_ohlcv(symbol, timeframe, limit=candles)
    except Exception as e:
        logger.warning("Backtest fetch_ohlcv failed: %s", e)
        return {"ok": False, "error": "No se pudieron cargar velas historicas"}

    if not ohlcv or len(ohlcv) < 10:
        return {"ok": False, "error": "Datos historicos insuficientes"}

    # Simulate
    position = SimulatedPosition(quote_balance=initial_quote)
    initial_value = initial_quote
    start_price = ohlcv[0][4]
    final_price = ohlcv[-1][4]
    position.peak_value = initial_quote

    # For DCA: only tick at intervals matching interval_hours
    dca_interval_hours = params.get("interval_hours", 24) if strategy_name == "dca" else 0
    tf_hours = {"5m": 1/12, "15m": 0.25, "1h": 1, "4h": 4, "1d": 24}.get(timeframe, 1)
    dca_tick_every = max(1, int(dca_interval_hours / tf_hours)) if dca_interval_hours else 1

    for i, c in enumerate(ohlcv):
        ts, o, h, low, cl, v = c
        ticker = Ticker(symbol=symbol, last=cl, bid=cl, ask=cl, high=h, low=low, timestamp=ts)

        # For DCA, tick only every N candles
        if strategy_name == "dca" and i % dca_tick_every != 0:
            position.mark_to_market(cl)
            continue

        try:
            orders = await strategy.tick(ticker)
        except Exception as e:
            logger.debug(f"Tick error at candle {i}: {e}")
            continue

        for order in orders:
            cost_usd = order.cost if order.cost else cl * order.amount
            amount = cost_usd / cl if order.side == "buy" else order.amount
            position.execute(order.side, amount, cl, ts)

        position.mark_to_market(cl)

    metrics = _compute_metrics(position, initial_value, final_price, start_price)

    return {
        "ok": True,
        "strategy": strategy_name,
        "symbol": symbol,
        "params": params_copy,
        "timeframe": timeframe,
        "candles_analyzed": len(ohlcv),
        "metrics": metrics,
        "trades": position.trades[-100:],  # last 100 for display
        "first_timestamp": ohlcv[0][0],
        "last_timestamp": ohlcv[-1][0],
    }
