import asyncio
import logging
from bot.notifications.email_notify import send_email
from bot.notifications.telegram_notify import send_telegram
from bot.notifications.config import load_channel

logger = logging.getLogger(__name__)


def _format_message(event_type: str, payload: dict) -> str:
    if event_type == "trade_executed":
        mode = "PAPER" if payload.get("is_paper") else "LIVE"
        return (
            f"[{mode}] {payload['side'].upper()} {payload['amount']:.8f} {payload['symbol']} "
            f"@ ${payload['price']:,.2f} (${payload['cost']:,.2f}) - {payload['strategy']}"
        )
    elif event_type == "strategy_started":
        return f"Strategy '{payload['strategy']}' started on {payload.get('symbol', '')}"
    elif event_type == "strategy_stopped":
        return f"Strategy '{payload['strategy']}' stopped"
    elif event_type == "strategy_error":
        return f"Error en '{payload['strategy']}': {payload['error']}"
    elif event_type == "risk_blocked":
        return f"Trade bloqueado por gestion de riesgo ({payload.get('strategy','?')}): {payload.get('reason','?')}"
    elif event_type == "kill_switch":
        return (
            f"KILL SWITCH activado. Estrategias detenidas: {len(payload.get('stopped', []))}. "
            f"Ordenes canceladas: {payload.get('cancelled_orders', 0)}"
        )
    else:
        return f"[{event_type}] {payload}"


async def notify(event_type: str, payload: dict):
    """Fire-and-forget notification to all enabled channels."""
    message = _format_message(event_type, payload)

    tg_config = await load_channel("telegram")
    email_config = await load_channel("email")

    tasks = []
    if tg_config.get("enabled") and tg_config.get("bot_token") and tg_config.get("chat_id"):
        tasks.append(_safe_send(send_telegram, message))
    if email_config.get("enabled") and email_config.get("smtp_host") and email_config.get("email_to"):
        subject = f"CryptoBot: {event_type.replace('_', ' ').title()}"
        tasks.append(_safe_send(send_email, subject, message))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _safe_send(func, *args):
    try:
        await func(*args)
    except Exception as e:
        logger.error(f"Notification failed: {e}")
