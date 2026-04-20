import logging
import re
from urllib.parse import quote

import aiohttp
from bot.notifications.config import load_channel

logger = logging.getLogger(__name__)

TELEGRAM_HOST = "https://api.telegram.org"
# Telegram bot tokens look like "<bot_id>:<35-char-secret>". Validate the shape
# before interpolating into a URL so CodeQL is satisfied that no path traversal
# or alternate host can be produced from a malicious token.
_TOKEN_RE = re.compile(r"^\d{5,20}:[A-Za-z0-9_-]{20,200}$")


def _telegram_url(token: str, method: str) -> str:
    if not _TOKEN_RE.match(token):
        raise ValueError("Formato de bot_token invalido")
    # quote() is belt-and-braces in case the regex is ever relaxed.
    return f"{TELEGRAM_HOST}/bot{quote(token, safe=':-_')}/{method}"


async def send_telegram(message: str):
    """Send a message using config from DB."""
    config = await load_channel("telegram")
    token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")

    if not token or not chat_id:
        return

    try:
        url = _telegram_url(token, "sendMessage")
    except ValueError:
        logger.error("Telegram send skipped: invalid bot_token shape")
        return
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown",
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                logger.info("Telegram message sent")
            else:
                text = await resp.text()
                logger.error("Telegram error (%s): %s", resp.status, text[:500])


async def send_telegram_with(token: str, chat_id: str, message: str) -> tuple[bool, str]:
    """Send a message with explicit credentials (used for testing). Returns (ok, error)."""
    if not token or not chat_id:
        return False, "Falta bot_token o chat_id"
    try:
        url = _telegram_url(token, "sendMessage")
    except ValueError:
        return False, "Formato de bot_token invalido"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return True, ""
                text = await resp.text()
                logger.warning("Telegram sendMessage %s: %s", resp.status, text[:500])
                return False, f"Telegram API devolvio {resp.status}"
    except Exception as e:
        logger.warning("Telegram network error: %s", e)
        return False, "Error de red al contactar Telegram"


async def validate_token(token: str) -> tuple[bool, dict]:
    """Check that the bot token is valid via getMe."""
    if not token:
        return False, {"error": "Token vacio"}
    try:
        url = _telegram_url(token, "getMe")
    except ValueError:
        return False, {"error": "Formato de bot_token invalido"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
                if resp.status == 200 and data.get("ok"):
                    bot = data.get("result", {})
                    return True, {
                        "username": bot.get("username", ""),
                        "first_name": bot.get("first_name", ""),
                        "id": bot.get("id"),
                    }
                description = data.get("description", "")
                logger.warning("Telegram getMe failure: %s", description[:200])
                return False, {"error": "Token rechazado por Telegram"}
    except Exception as e:
        logger.warning("Telegram validate_token network error: %s", e)
        return False, {"error": "Error de red al contactar Telegram"}


async def detect_chat_id(token: str) -> tuple[str | None, list]:
    """Try to auto-detect chat_id from recent messages sent to the bot.
    Returns (chat_id, list_of_recent_chats)."""
    if not token:
        return None, []
    try:
        url = _telegram_url(token, "getUpdates")
    except ValueError:
        return None, []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status != 200:
                    return None, []
                data = await resp.json()
                updates = data.get("result", [])
                if not updates:
                    return None, []

                # Collect unique chats (most recent first)
                seen: dict[str, dict] = {}
                for u in reversed(updates):
                    msg = u.get("message") or u.get("edited_message") or {}
                    chat = msg.get("chat", {})
                    cid = str(chat.get("id", ""))
                    if cid and cid not in seen:
                        seen[cid] = {
                            "id": cid,
                            "type": chat.get("type", ""),
                            "title": chat.get("title") or chat.get("username") or chat.get("first_name", ""),
                        }

                chats = list(seen.values())
                return chats[0]["id"] if chats else None, chats
    except Exception as e:
        logger.error("detect_chat_id error: %s", e)
        return None, []
