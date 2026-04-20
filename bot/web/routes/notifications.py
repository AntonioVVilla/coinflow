import logging

from fastapi import APIRouter
from pydantic import BaseModel
from bot.notifications.config import load_channel, save_channel, delete_channel
from bot.notifications.telegram_notify import (
    validate_token, detect_chat_id, send_telegram_with,
)
from bot.notifications.email_notify import send_email_test
from bot.notifications.telegram_listener import restart_listener

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


# ============== TELEGRAM ==============

class TelegramConfig(BaseModel):
    bot_token: str
    chat_id: str = ""


class TokenOnly(BaseModel):
    bot_token: str


@router.get("/telegram/commands")
async def list_telegram_commands():
    """Returns the list of available Telegram bot commands."""
    return {"commands": [
        {"cmd": "/start", "desc": "Saludo inicial y bienvenida"},
        {"cmd": "/help", "desc": "Lista de todos los comandos"},
        {"cmd": "/status", "desc": "Resumen del portfolio (balance + modo + estrategias)"},
        {"cmd": "/balance", "desc": "Balances por activo"},
        {"cmd": "/prices", "desc": "Precios actuales de BTC y ETH"},
        {"cmd": "/trades", "desc": "Ultimos 5 trades"},
        {"cmd": "/strategies", "desc": "Estado de las estrategias (configurada / corriendo)"},
        {"cmd": "/mode", "desc": "Modo actual (PAPER o LIVE)"},
        {"cmd": "/start_strategy <nombre>", "desc": "Iniciar estrategia (grid, dca, webhook)"},
        {"cmd": "/stop_strategy <nombre>", "desc": "Detener una estrategia"},
        {"cmd": "/tick <nombre>", "desc": "Ejecutar tick ahora (ej: /tick dca = comprar ya)"},
        {"cmd": "/pause", "desc": "Pausar todo trading 1 hora (circuit breaker)"},
        {"cmd": "/resume", "desc": "Reanudar trading tras pausa"},
        {"cmd": "/stop_all", "desc": "KILL SWITCH: detener todo + cancelar ordenes"},
    ]}


@router.get("/telegram")
async def get_telegram():
    config = await load_channel("telegram")
    # Never return the full token; just a hint
    token = config.get("bot_token", "")
    return {
        "configured": bool(token),
        "enabled": config.get("enabled", False),
        "chat_id": config.get("chat_id", ""),
        "bot_username": config.get("bot_username", ""),
        "token_hint": (token[:6] + "..." + token[-4:]) if len(token) > 12 else "",
    }


@router.post("/telegram/validate")
async def validate_telegram_token(data: TokenOnly):
    """Validate that a bot token is real. Does NOT save."""
    ok, info = await validate_token(data.bot_token)
    if ok:
        return {"valid": True, "bot": info}
    # validate_token already logs the real cause; return a sanitized message.
    return {"valid": False, "error": "Token invalido"}


@router.post("/telegram/detect-chat")
async def detect_telegram_chat(data: TokenOnly):
    """Detect chat_id from recent messages sent to the bot."""
    chat_id, chats = await detect_chat_id(data.bot_token)
    if not chat_id:
        return {
            "ok": False,
            "error": "No se encontraron mensajes. Envia /start a tu bot primero desde Telegram.",
        }
    return {"ok": True, "chat_id": chat_id, "chats": chats}


@router.post("/telegram/test")
async def test_telegram(data: TelegramConfig):
    """Send a test message with provided credentials."""
    msg = "✅ CryptoBot conectado correctamente a Telegram"
    ok, err = await send_telegram_with(data.bot_token, data.chat_id, msg)
    if ok:
        return {"ok": True, "error": ""}
    logger.info("Telegram test failed: %s", err)
    return {"ok": False, "error": "No se pudo enviar el mensaje de prueba"}


@router.post("/daily-summary/send")
async def trigger_daily_summary():
    """Fire the daily summary right now (for testing or on-demand)."""
    from bot.engine.daily_summary import send_daily_summary
    await send_daily_summary()
    return {"ok": True, "message": "Resumen enviado a los canales activos"}


@router.post("/telegram/test-saved")
async def test_telegram_saved():
    """Send a test message using the currently saved config."""
    config = await load_channel("telegram")
    token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")
    if not token or not chat_id:
        return {"ok": False, "error": "No hay configuracion guardada"}
    ok, err = await send_telegram_with(token, chat_id, "✅ Prueba desde CryptoBot")
    if ok:
        return {"ok": True, "error": ""}
    logger.info("Telegram saved-config test failed: %s", err)
    return {"ok": False, "error": "No se pudo enviar el mensaje de prueba"}


@router.post("/telegram/save")
async def save_telegram(data: TelegramConfig):
    """Validate, test, then save config encrypted in DB."""
    # Validate token
    ok, info = await validate_token(data.bot_token)
    if not ok:
        return {"ok": False, "error": "Token invalido"}

    # Test send
    sent, err = await send_telegram_with(data.bot_token, data.chat_id, "✅ CryptoBot conectado")
    if not sent:
        logger.info("Telegram save test failed: %s", err)
        return {"ok": False, "error": "Prueba de envio fallida"}

    # Save
    await save_channel("telegram", enabled=True, config={
        "bot_token": data.bot_token,
        "chat_id": data.chat_id,
        "bot_username": info.get("username", ""),
    })
    # Restart listener so it picks up the new token
    await restart_listener()
    return {"ok": True, "bot_username": info.get("username", "")}


@router.post("/telegram/toggle")
async def toggle_telegram():
    config = await load_channel("telegram")
    if not config.get("bot_token"):
        return {"ok": False, "error": "No hay configuracion de Telegram"}
    new_state = not config.get("enabled", False)
    await save_channel("telegram", enabled=new_state, config={
        k: v for k, v in config.items() if k != "enabled"
    })
    await restart_listener()
    return {"ok": True, "enabled": new_state}


@router.delete("/telegram")
async def delete_telegram():
    await delete_channel("telegram")
    await restart_listener()
    return {"ok": True}


# ============== EMAIL ==============

class EmailConfig(BaseModel):
    smtp_host: str
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    email_to: str


@router.get("/email")
async def get_email():
    config = await load_channel("email")
    return {
        "configured": bool(config.get("smtp_host")),
        "enabled": config.get("enabled", False),
        "smtp_host": config.get("smtp_host", ""),
        "smtp_port": config.get("smtp_port", 587),
        "smtp_user": config.get("smtp_user", ""),
        "email_to": config.get("email_to", ""),
        # Never expose smtp_pass
        "has_password": bool(config.get("smtp_pass")),
    }


@router.post("/email/test")
async def test_email(data: EmailConfig):
    ok, err = await send_email_test(
        data.model_dump(),
        "CryptoBot: prueba de conexion",
        "Si recibes este mensaje, el SMTP esta configurado correctamente.",
    )
    if ok:
        return {"ok": True, "error": ""}
    logger.info("Email test failed: %s", err)
    return {"ok": False, "error": "No se pudo enviar el correo de prueba"}


@router.post("/email/save")
async def save_email(data: EmailConfig):
    # Test first
    ok, err = await send_email_test(
        data.model_dump(),
        "CryptoBot: conectado",
        "SMTP configurado correctamente.",
    )
    if not ok:
        logger.info("Email save test failed: %s", err)
        return {"ok": False, "error": "Prueba de envio fallida"}

    await save_channel("email", enabled=True, config=data.model_dump())
    return {"ok": True}


@router.post("/email/toggle")
async def toggle_email():
    config = await load_channel("email")
    if not config.get("smtp_host"):
        return {"ok": False, "error": "No hay configuracion de Email"}
    new_state = not config.get("enabled", False)
    await save_channel("email", enabled=new_state, config={
        k: v for k, v in config.items() if k != "enabled"
    })
    return {"ok": True, "enabled": new_state}


@router.delete("/email")
async def delete_email():
    await delete_channel("email")
    return {"ok": True}
