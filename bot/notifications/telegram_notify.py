import logging
import aiohttp
from bot.notifications.config import load_channel

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


async def send_telegram(message: str):
    """Send a message using config from DB."""
    config = await load_channel("telegram")
    token = config.get("bot_token", "")
    chat_id = config.get("chat_id", "")

    if not token or not chat_id:
        return

    url = TELEGRAM_API.format(token=token)
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
                logger.error(f"Telegram error ({resp.status}): {text}")


async def send_telegram_with(token: str, chat_id: str, message: str) -> tuple[bool, str]:
    """Send a message with explicit credentials (used for testing). Returns (ok, error)."""
    if not token or not chat_id:
        return False, "Falta bot_token o chat_id"
    url = TELEGRAM_API.format(token=token)
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    return True, ""
                text = await resp.text()
                return False, f"Telegram API ({resp.status}): {text[:200]}"
    except Exception as e:
        return False, f"Error de red: {e}"


async def validate_token(token: str) -> tuple[bool, dict]:
    """Check that the bot token is valid via getMe."""
    if not token:
        return False, {"error": "Token vacio"}
    url = f"https://api.telegram.org/bot{token}/getMe"
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
                return False, {"error": data.get("description", "Token invalido")}
    except Exception as e:
        return False, {"error": f"Error de red: {e}"}


async def detect_chat_id(token: str) -> tuple[str | None, list]:
    """Try to auto-detect chat_id from recent messages sent to the bot.
    Returns (chat_id, list_of_recent_chats)."""
    if not token:
        return None, []
    url = f"https://api.telegram.org/bot{token}/getUpdates"
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
        logger.error(f"detect_chat_id error: {e}")
        return None, []
