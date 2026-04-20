import json
import logging
from sqlalchemy import select
from bot.database import async_session
from bot.models import StrategyConfig, Trade
from bot.config import settings
from bot.exchange.client import CoinbaseClient
from bot.exchange.paper import PaperClient
from bot.exchange.schemas import OrderRequest
from bot.log_utils import safe
from bot.strategies.base import BaseStrategy
from bot.strategies.grid import GridStrategy
from bot.strategies.dca import DCAStrategy
from bot.strategies.webhook import WebhookStrategy
from bot.engine import scheduler as sched
from bot.notifications.dispatcher import notify

logger = logging.getLogger(__name__)

STRATEGY_CLASSES: dict[str, type[BaseStrategy]] = {
    "grid": GridStrategy,
    "dca": DCAStrategy,
    "webhook": WebhookStrategy,
}

_active_strategies: dict[str, BaseStrategy] = {}
_exchange_client: PaperClient | CoinbaseClient | None = None


def get_exchange_client():
    global _exchange_client
    return _exchange_client


async def init_exchange(api_key: str = "", api_secret: str = ""):
    global _exchange_client
    if _exchange_client:
        await _exchange_client.close()

    if settings.paper_mode or not api_key:
        _exchange_client = PaperClient()
        logger.info("Exchange: Paper trading mode")
    else:
        _exchange_client = CoinbaseClient(api_key, api_secret)
        logger.info("Exchange: Live Coinbase mode")


async def _execute_orders(strategy_name: str, orders: list[OrderRequest]) -> list[dict]:
    """Execute a list of orders. Returns a list of per-order results with status."""
    results: list[dict] = []
    client = get_exchange_client()
    if not client or not orders:
        return results

    from bot.engine.risk import check_pre_trade
    strategy_obj = _active_strategies.get(strategy_name)

    for req in orders:
        try:
            ticker = await client.fetch_ticker(req.symbol)
            est_cost = ticker.last * req.amount

            allowed, reason = await check_pre_trade(strategy_name, req.side, req.symbol, est_cost)
            if not allowed:
                logger.warning("Trade blocked by risk mgmt (%s): %s", safe(strategy_name), safe(reason))
                await notify("risk_blocked", {"strategy": strategy_name, "reason": reason})
                results.append({
                    "ok": False, "status": "risk_blocked",
                    "error": reason,
                    "side": req.side, "symbol": req.symbol, "amount": req.amount,
                })
                if strategy_obj and hasattr(strategy_obj, "on_trade_failed"):
                    try:
                        await strategy_obj.on_trade_failed(req, reason)
                    except Exception as cb_err:
                        logger.debug(f"on_trade_failed callback error: {cb_err}")
                continue

            result = await client.create_order(req)
            # Save trade to DB (with error handling - order already executed on exchange)
            try:
                async with async_session() as session:
                    trade = Trade(
                        strategy=strategy_name,
                        symbol=result.symbol,
                        side=result.side,
                        order_type=result.order_type,
                        amount=result.amount,
                        price=result.price,
                        cost=result.cost,
                        fee=result.fee,
                        order_id=result.order_id,
                        is_paper=settings.paper_mode,
                        status=result.status,
                    )
                    session.add(trade)
                    await session.commit()
            except Exception as db_err:
                logger.error(f"Trade {result.order_id} executed but DB save failed: {db_err}")
                await notify("strategy_error", {
                    "strategy": strategy_name,
                    "error": f"Trade ejecutado (ID:{result.order_id}) pero no se guardo en DB: {db_err}. Usa 'Sincronizar' en Cuenta para recuperarlo.",
                })

            trade_event = {
                "strategy": strategy_name,
                "side": result.side,
                "amount": result.amount,
                "symbol": result.symbol,
                "price": result.price,
                "cost": result.cost,
                "is_paper": settings.paper_mode,
            }
            await notify("trade_executed", trade_event)

            try:
                from bot.web.routes.websocket import broadcast
                await broadcast("trade", trade_event)
            except Exception as ws_err:
                logger.debug(f"Websocket broadcast failed: {ws_err}")

            # Notify strategy of success
            if strategy_obj and hasattr(strategy_obj, "on_trade_executed"):
                try:
                    await strategy_obj.on_trade_executed(result)
                except Exception as cb_err:
                    logger.debug(f"on_trade_executed callback error: {cb_err}")

            results.append({
                "ok": True, "status": "filled",
                "side": result.side, "symbol": result.symbol,
                "amount": result.amount, "price": result.price,
                "cost": result.cost, "fee": result.fee,
                "order_id": result.order_id,
            })
        except Exception as e:
            err_str = str(e)
            # Parse common Coinbase errors for clarity
            friendly = err_str
            low = err_str.lower()
            if "insufficient" in low or "not enough" in low:
                quote = req.symbol.split("/")[1]
                friendly = f"Saldo insuficiente de {quote} para comprar {req.symbol}. Detalle: {err_str[:200]}"
            elif "minimum" in low or "min size" in low:
                friendly = f"Cantidad menor al minimo permitido por Coinbase. Detalle: {err_str[:200]}"
            elif "permission" in low or "unauthorized" in low:
                friendly = f"Permisos insuficientes en la API key. Detalle: {err_str[:200]}"

            logger.error("Order execution failed (%s): %s", safe(strategy_name), safe(err_str))
            await notify("strategy_error", {"strategy": strategy_name, "error": friendly})
            results.append({
                "ok": False, "status": "error",
                "error": friendly,
                "side": req.side, "symbol": req.symbol, "amount": req.amount,
            })
            if strategy_obj and hasattr(strategy_obj, "on_trade_failed"):
                try:
                    await strategy_obj.on_trade_failed(req, friendly)
                except Exception as cb_err:
                    logger.debug(f"on_trade_failed callback error: {cb_err}")

    return results


async def _strategy_tick(strategy_name: str, symbol: str):
    strategy = _active_strategies.get(strategy_name)
    client = get_exchange_client()
    if not strategy or not client:
        return

    try:
        ticker = await client.fetch_ticker(symbol)
        orders = await strategy.tick(ticker)
        await _execute_orders(strategy_name, orders)
    except Exception as e:
        logger.error("Strategy tick error (%s): %s", safe(strategy_name), safe(e))


async def start_strategy(name: str, symbol: str, params: dict) -> bool:
    if name in _active_strategies:
        logger.warning("Strategy '%s' already running", safe(name))
        return False

    cls = STRATEGY_CLASSES.get(name)
    if not cls:
        logger.error("Unknown strategy: %s", safe(name))
        return False

    strategy = cls()
    params["symbol"] = symbol
    await strategy.setup(params)
    _active_strategies[name] = strategy

    # Schedule tick jobs (webhook is event-driven, no tick)
    if name == "grid":
        sched.add_job(
            f"strategy_{name}",
            lambda: _strategy_tick(name, symbol),
            seconds=settings.grid_tick_seconds,
        )
    elif name == "dca":
        interval_hours = params.get("interval_hours", 24)
        sched.add_job(
            f"strategy_{name}",
            lambda: _strategy_tick(name, symbol),
            hours=interval_hours,
        )

    logger.info("Strategy '%s' started", safe(name))
    await notify("strategy_started", {"strategy": name, "symbol": symbol})
    return True


async def stop_strategy(name: str) -> bool:
    strategy = _active_strategies.pop(name, None)
    if not strategy:
        return False

    await strategy.teardown()
    sched.remove_job(f"strategy_{name}")
    logger.info("Strategy '%s' stopped", safe(name))
    await notify("strategy_stopped", {"strategy": name})
    return True


async def force_tick(name: str) -> dict:
    """Manually trigger a strategy tick. Returns detailed per-order results.

    Safety net: if the strategy instance has a stale config (different from DB),
    restart it before ticking. This prevents the user from being confused by
    cached params after they edited them in the UI.
    """
    strategy = _active_strategies.get(name)
    if not strategy:
        return {"ok": False, "error": f"Estrategia '{name}' no esta corriendo", "results": []}

    client = get_exchange_client()
    if not client:
        return {"ok": False, "error": "Exchange no inicializado", "results": []}

    # Reload config from DB and compare with running instance
    async with async_session() as session:
        result = await session.execute(
            select(StrategyConfig).where(StrategyConfig.name == name)
        )
        db_config = result.scalar_one_or_none()

    if db_config:
        db_params = json.loads(db_config.params)
        current_symbol = getattr(strategy, "symbol", "")
        # Symbol changed? Restart with new config
        if db_config.symbol != current_symbol:
            logger.info(
                "Strategy '%s' config changed (symbol: %s -> %s), restarting",
                safe(name), safe(current_symbol), safe(db_config.symbol),
            )
            await stop_strategy(name)
            await start_strategy(name, db_config.symbol, db_params)
            strategy = _active_strategies.get(name)
            if not strategy:
                return {"ok": False, "error": "No se pudo reiniciar la estrategia", "results": []}

    try:
        symbol = getattr(strategy, "symbol", "BTC/USD")
        ticker = await client.fetch_ticker(symbol)
        orders = await strategy.tick(ticker)
        if not orders:
            return {
                "ok": True, "orders": 0, "filled": 0, "failed": 0,
                "message": f"Tick ejecutado. Precio actual: ${ticker.last:,.2f}. La estrategia decidio no emitir ordenes en este momento.",
                "results": [],
            }

        results = await _execute_orders(name, orders)
        filled = sum(1 for r in results if r.get("ok"))
        failed = sum(1 for r in results if not r.get("ok"))

        # Overall status
        overall_ok = failed == 0 and filled > 0
        if filled > 0 and failed == 0:
            message = f"✅ {filled} orden(es) ejecutada(s) correctamente"
        elif filled > 0 and failed > 0:
            message = f"⚠️ {filled} exitosa(s), {failed} fallida(s)"
        else:
            message = f"❌ {failed} orden(es) fallaron. Ver detalles."

        return {
            "ok": overall_ok, "orders": len(orders),
            "filled": filled, "failed": failed,
            "message": message, "results": results,
        }
    except Exception as e:
        logger.exception("force_tick error (%s): %s", safe(name), safe(e))
        return {"ok": False, "error": "No se pudo ejecutar el tick", "results": []}


def get_strategy_status(name: str) -> dict | None:
    strategy = _active_strategies.get(name)
    if strategy:
        return {**strategy.get_status(), "running": True}
    return None


def get_all_statuses() -> dict:
    return {
        name: {**s.get_status(), "running": True}
        for name, s in _active_strategies.items()
    }


def get_webhook_strategy() -> WebhookStrategy | None:
    s = _active_strategies.get("webhook")
    return s if isinstance(s, WebhookStrategy) else None


async def kill_switch() -> dict:
    """EMERGENCY: Stop all strategies and cancel all open orders."""
    logger.warning("KILL SWITCH ACTIVATED")
    stopped = []
    errors = []

    # Stop all running strategies
    for name in list(_active_strategies.keys()):
        try:
            await stop_strategy(name)
            stopped.append(name)
        except Exception as e:
            logger.error("kill_switch stop_strategy(%s) failed: %s", safe(name), safe(e))
            errors.append(f"stop {safe(name)}: fallo")

    # Deactivate in DB so they don't restart
    async with async_session() as session:
        result = await session.execute(select(StrategyConfig))
        for config in result.scalars().all():
            config.is_active = False
        await session.commit()

    # Cancel all open orders on the exchange
    client = get_exchange_client()
    cancelled = 0
    if client and hasattr(client, "_exchange"):
        try:
            for symbol in settings.supported_symbols:
                try:
                    orders = await client._exchange.fetch_open_orders(symbol)
                    for o in orders:
                        try:
                            await client.cancel_order(o["id"], symbol)
                            cancelled += 1
                        except Exception as e:
                            logger.error("kill_switch cancel %s: %s", o.get("id"), safe(e))
                            errors.append(f"cancel {safe(o.get('id'))}: fallo")
                except Exception as e:
                    logger.error("kill_switch fetch_open_orders %s: %s", safe(symbol), safe(e))
                    errors.append(f"fetch_open_orders {safe(symbol)}: fallo")
        except Exception as e:
            logger.error("kill_switch cancel_loop: %s", safe(e))
            errors.append("cancel_loop: fallo")

    await notify("kill_switch", {"stopped": stopped, "cancelled_orders": cancelled})
    return {"stopped_strategies": stopped, "cancelled_orders": cancelled, "errors": errors}


async def load_active_strategies():
    """Load and start strategies that were active before restart."""
    async with async_session() as session:
        result = await session.execute(
            select(StrategyConfig).where(StrategyConfig.is_active.is_(True))
        )
        configs = result.scalars().all()

    for config in configs:
        params = json.loads(config.params)
        await start_strategy(config.name, config.symbol, params)
        logger.info("Restored strategy '%s' from DB", safe(config.name))
