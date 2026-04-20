"""Telegram command listener (long polling).

Starts a background task that polls Telegram's getUpdates API and dispatches
commands. Only accepts messages from the configured chat_id.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Awaitable

import aiohttp
from sqlalchemy import select, desc

from bot.database import async_session
from bot.models import Trade, RiskConfig, StrategyConfig
from bot.notifications.config import load_channel
from bot.engine.runner import (
    get_exchange_client, get_all_statuses, start_strategy,
    stop_strategy, kill_switch, force_tick, STRATEGY_CLASSES,
)
from bot.config import settings

logger = logging.getLogger(__name__)

# State
_task: asyncio.Task | None = None
_last_update_id: int = 0
_running: bool = False


# ================== COMMAND HANDLERS ==================

async def _send(token: str, chat_id: str, text: str, parse_mode: str = "Markdown"):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(
                url,
                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
                timeout=aiohttp.ClientTimeout(total=10),
            )
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")


async def cmd_start(args: list[str]) -> str:
    return (
        "🤖 *CryptoBot* conectado\n\n"
        "Comandos disponibles. Envia /help para verlos todos."
    )


async def cmd_help(args: list[str]) -> str:
    return (
        "*📋 Comandos disponibles*\n\n"
        "*📊 Consulta:*\n"
        "/status — resumen del portfolio\n"
        "/balance — balances por activo\n"
        "/prices — precios actuales BTC y ETH\n"
        "/trades — ultimos 5 trades\n"
        "/strategies — estado de estrategias\n"
        "/mode — modo actual (PAPER/LIVE)\n\n"
        "*⚙️ Control:*\n"
        "/start\\_strategy `<nombre>` — iniciar (grid/dca/webhook)\n"
        "/stop\\_strategy `<nombre>` — detener estrategia\n"
        "/tick `<nombre>` — ejecutar tick ahora (comprar ya en DCA)\n"
        "/pause — pausar todo trading 1 hora\n"
        "/resume — reanudar trading\n\n"
        "*⚠️ Emergencia:*\n"
        "/stop\\_all — kill switch (detiene todo + cancela ordenes)\n\n"
        "/help — esta ayuda"
    )


async def cmd_status(args: list[str]) -> str:
    client = get_exchange_client()
    if not client:
        return "⚠️ Exchange no inicializado"

    try:
        balances = await client.fetch_balance()
        balance_map = {b.currency: b.total for b in balances}

        prices = {}
        total_usd = balance_map.get("USD", 0) or 0
        for sym in settings.supported_symbols:
            try:
                t = await client.fetch_ticker(sym)
                prices[sym] = t.last
                base = sym.split("/")[0]
                total_usd += (balance_map.get(base, 0) or 0) * t.last
            except Exception as ticker_err:
                logger.debug(f"Ticker fetch failed for {sym}: {ticker_err}")

        mode = "🟡 PAPER" if settings.paper_mode else "🟢 LIVE"
        running = get_all_statuses()

        lines = [
            "*📊 Portfolio*",
            f"Total: *${total_usd:,.2f}*",
            f"Modo: {mode}",
            "",
        ]
        for cur, val in sorted(balance_map.items()):
            if val and val > 0:
                lines.append(f"  {cur}: `{val:.8f}`")
        lines.append("")
        lines.append(f"*Estrategias activas:* {len(running)}")
        for name in running:
            lines.append(f"  • {name}")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error: {e}"


async def cmd_balance(args: list[str]) -> str:
    client = get_exchange_client()
    if not client:
        return "⚠️ Exchange no inicializado"
    try:
        balances = await client.fetch_balance()
        if not balances:
            return "Sin saldos"
        lines = ["*💰 Balances*"]
        for b in balances:
            lines.append(f"`{b.currency}`: {b.total:.8f}")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error: {e}"


async def cmd_prices(args: list[str]) -> str:
    client = get_exchange_client()
    if not client:
        return "⚠️ Exchange no inicializado"
    try:
        lines = ["*💹 Precios actuales*"]
        for sym in settings.supported_symbols:
            try:
                t = await client.fetch_ticker(sym)
                lines.append(f"*{sym}*: `${t.last:,.2f}`")
            except Exception as ticker_err:
                logger.debug(f"Ticker fetch failed for {sym}: {ticker_err}")
        return "\n".join(lines)
    except Exception as e:
        return f"⚠️ Error: {e}"


async def cmd_trades(args: list[str]) -> str:
    async with async_session() as session:
        result = await session.execute(
            select(Trade).order_by(desc(Trade.created_at)).limit(5)
        )
        trades = result.scalars().all()

    if not trades:
        return "Sin trades aun"

    lines = ["*📜 Ultimos 5 trades*"]
    for t in trades:
        emoji = "🟢" if t.side == "buy" else "🔴"
        when = t.created_at.strftime("%m-%d %H:%M")
        lines.append(
            f"{emoji} `{when}` {t.side.upper()} {t.amount:.6f} {t.symbol} "
            f"@ ${t.price:,.2f} = ${t.cost:,.2f} _({t.strategy})_"
        )
    return "\n".join(lines)


async def cmd_strategies(args: list[str]) -> str:
    async with async_session() as session:
        result = await session.execute(select(StrategyConfig))
        configs = result.scalars().all()

    running = get_all_statuses()
    lines = ["*⚙️ Estrategias*"]
    for name in STRATEGY_CLASSES:
        config = next((c for c in configs if c.name == name), None)
        is_running = name in running
        state = "🟢 CORRIENDO" if is_running else ("🟡 CONFIGURADA" if config else "⚪ NO CONFIGURADA")
        symbol = config.symbol if config else "-"
        lines.append(f"*{name.upper()}* — {state} ({symbol})")
    return "\n".join(lines)


async def cmd_mode(args: list[str]) -> str:
    mode = "🟡 PAPER (simulado)" if settings.paper_mode else "🟢 LIVE (dinero real)"
    return f"*Modo actual:* {mode}"


async def cmd_start_strategy(args: list[str]) -> str:
    if not args:
        return "Uso: `/start_strategy <nombre>`\nEjemplo: `/start_strategy dca`\n\nNombres: grid, dca, webhook"
    name = args[0].lower()
    if name not in STRATEGY_CLASSES:
        return f"⚠️ Estrategia desconocida: `{name}`\nDisponibles: {', '.join(STRATEGY_CLASSES.keys())}"

    async with async_session() as session:
        result = await session.execute(select(StrategyConfig).where(StrategyConfig.name == name))
        config = result.scalar_one_or_none()
        if not config:
            return f"⚠️ Configura primero `{name}` desde el dashboard"

        try:
            params = json.loads(config.params)
        except Exception:
            params = {}

        if await start_strategy(name, config.symbol, params):
            config.is_active = True
            await session.commit()
            return f"✅ Estrategia `{name}` iniciada en {config.symbol}"
        return f"⚠️ `{name}` ya esta corriendo"


async def cmd_stop_strategy(args: list[str]) -> str:
    if not args:
        return "Uso: `/stop_strategy <nombre>`"
    name = args[0].lower()
    async with async_session() as session:
        result = await session.execute(select(StrategyConfig).where(StrategyConfig.name == name))
        config = result.scalar_one_or_none()
    if await stop_strategy(name):
        if config:
            async with async_session() as session:
                result = await session.execute(select(StrategyConfig).where(StrategyConfig.name == name))
                c = result.scalar_one_or_none()
                if c:
                    c.is_active = False
                    await session.commit()
        return f"🛑 Estrategia `{name}` detenida"
    return f"⚠️ `{name}` no estaba corriendo"


async def cmd_tick(args: list[str]) -> str:
    if not args:
        return "Uso: `/tick <estrategia>`\nEjemplo: `/tick dca` para comprar ahora\nNombres: grid, dca"
    name = args[0].lower()
    res = await force_tick(name)

    if res.get("error") and not res.get("results"):
        return f"⚠️ *Error:* {res['error']}"

    orders = res.get("orders", 0)
    results = res.get("results", [])
    filled = res.get("filled", 0)
    failed = res.get("failed", 0)

    if orders == 0:
        return f"ℹ️ Tick en `{name}` ejecutado, *sin ordenes generadas* (la estrategia decidio no operar ahora)"

    lines = [f"*Tick en `{name}`*", f"Ordenes: {orders} ({filled} OK, {failed} fallidas)", ""]
    for r in results:
        if r.get("ok"):
            lines.append(
                f"✅ {r['side'].upper()} `{r['amount']:.8f}` {r['symbol']} "
                f"@ ${r['price']:,.2f} = ${r['cost']:,.2f}"
            )
            if r.get("order_id"):
                lines.append(f"   _Order ID:_ `{r['order_id']}`")
        else:
            lines.append(
                f"❌ {r['side'].upper()} `{r['amount']:.8f}` {r['symbol']} *FALLO*"
            )
            lines.append(f"   _Motivo:_ {r.get('error', '?')[:200]}")
    return "\n".join(lines)


async def cmd_pause(args: list[str]) -> str:
    pause_until = datetime.now(timezone.utc) + timedelta(hours=1)
    async with async_session() as session:
        result = await session.execute(select(RiskConfig).limit(1))
        rc = result.scalar_one_or_none()
        if not rc:
            rc = RiskConfig(enabled=True)
            session.add(rc)
        rc.paused_until = pause_until
        rc.enabled = True
        await session.commit()
    return f"⏸ Trading pausado hasta `{pause_until.strftime('%H:%M UTC')}` (1 hora)"


async def cmd_resume(args: list[str]) -> str:
    async with async_session() as session:
        result = await session.execute(select(RiskConfig).limit(1))
        rc = result.scalar_one_or_none()
        if rc:
            rc.paused_until = None
            await session.commit()
    return "▶️ Trading reanudado"


async def cmd_stop_all(args: list[str]) -> str:
    result = await kill_switch()
    stopped = result.get("stopped_strategies", [])
    cancelled = result.get("cancelled_orders", 0)
    return (
        f"🚨 *KILL SWITCH ACTIVADO*\n\n"
        f"Estrategias detenidas: {len(stopped)}\n"
        f"Ordenes canceladas: {cancelled}\n"
    )


# Command registry
COMMANDS: dict[str, Callable[[list[str]], Awaitable[str]]] = {
    "/start": cmd_start,
    "/help": cmd_help,
    "/status": cmd_status,
    "/balance": cmd_balance,
    "/prices": cmd_prices,
    "/trades": cmd_trades,
    "/strategies": cmd_strategies,
    "/mode": cmd_mode,
    "/start_strategy": cmd_start_strategy,
    "/stop_strategy": cmd_stop_strategy,
    "/tick": cmd_tick,
    "/buy_now": cmd_tick,
    "/pause": cmd_pause,
    "/resume": cmd_resume,
    "/stop_all": cmd_stop_all,
    "/killswitch": cmd_stop_all,
}


# ================== LISTENER LOOP ==================

async def _process_message(token: str, allowed_chat_id: str, message: dict):
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    text = (message.get("text") or "").strip()
    from_user = message.get("from", {})
    username = from_user.get("username") or from_user.get("first_name", "?")

    # Security: only allow the configured chat_id
    if chat_id != str(allowed_chat_id):
        logger.warning(f"Telegram: unauthorized chat_id={chat_id} user={username}")
        # Send a polite rejection (this tells the attacker we're here, but it's a bot so OK)
        await _send(token, chat_id, "🚫 No autorizado. Este bot solo acepta comandos de su duenio.")
        return

    if not text.startswith("/"):
        return  # Ignore non-commands

    # Strip bot mention: /status@mybot -> /status
    parts = text.split()
    cmd = parts[0].split("@")[0].lower()
    args = parts[1:]

    handler = COMMANDS.get(cmd)
    if not handler:
        await _send(token, chat_id, f"❓ Comando desconocido: `{cmd}`\nEnvia /help")
        return

    try:
        response = await handler(args)
        await _send(token, chat_id, response)
        logger.info(f"Telegram cmd handled: {cmd} by {username}")
    except Exception as e:
        logger.exception(f"Telegram cmd error ({cmd}): {e}")
        await _send(token, chat_id, f"⚠️ Error ejecutando {cmd}: {e}")


async def _poll_loop():
    global _last_update_id
    logger.info("Telegram listener started")

    while _running:
        try:
            config = await load_channel("telegram")
            if not config.get("enabled") or not config.get("bot_token") or not config.get("chat_id"):
                # Listener was disabled - sleep a bit and check again
                await asyncio.sleep(5)
                continue

            token = config["bot_token"]
            chat_id = config["chat_id"]

            url = f"https://api.telegram.org/bot{token}/getUpdates"
            params = {"timeout": 25, "offset": _last_update_id + 1 if _last_update_id else 0}

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=35),
                ) as resp:
                    if resp.status != 200:
                        logger.warning(f"Telegram getUpdates status {resp.status}")
                        await asyncio.sleep(10)
                        continue
                    data = await resp.json()

            if not data.get("ok"):
                logger.warning(f"Telegram API error: {data.get('description')}")
                await asyncio.sleep(10)
                continue

            for update in data.get("result", []):
                _last_update_id = update["update_id"]
                message = update.get("message") or update.get("edited_message")
                if message and message.get("text"):
                    await _process_message(token, chat_id, message)

        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            pass  # long-poll timeout is normal
        except Exception as e:
            logger.error(f"Telegram poll loop error: {e}")
            await asyncio.sleep(5)

    logger.info("Telegram listener stopped")


def start_listener():
    """Start the background poller if not already running."""
    global _task, _running
    if _task and not _task.done():
        return
    _running = True
    _task = asyncio.create_task(_poll_loop())


def stop_listener():
    global _task, _running
    _running = False
    if _task and not _task.done():
        _task.cancel()


async def restart_listener():
    """Called after config changes to pick up new token."""
    global _last_update_id
    stop_listener()
    _last_update_id = 0
    await asyncio.sleep(0.5)
    start_listener()
