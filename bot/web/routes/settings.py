from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.web.deps import get_db
from bot.models import ApiKey
from bot.security import encrypt, decrypt
from bot.exchange.client import CoinbaseClient
from bot.engine.runner import init_exchange
from bot.config import settings

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ExchangeKeys(BaseModel):
    api_key: str
    api_secret: str


class NotificationConfig(BaseModel):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_pass: str = ""
    email_to: str = ""


@router.get("/exchange")
async def get_exchange_status(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.exchange == "coinbase"))
    key = result.scalar_one_or_none()
    return {
        "configured": key is not None and key.is_valid,
        "exchange": "coinbase",
        "paper_mode": settings.paper_mode,
    }


@router.post("/exchange/validate")
async def validate_exchange_keys(data: ExchangeKeys):
    client = CoinbaseClient(data.api_key, data.api_secret)
    try:
        result = await client.validate_keys()
        return result
    finally:
        await client.close()


@router.post("/exchange/save")
async def save_exchange_keys(data: ExchangeKeys, db: AsyncSession = Depends(get_db)):
    # Validate first
    client = CoinbaseClient(data.api_key, data.api_secret)
    try:
        result = await client.validate_keys()
        if not result["valid"]:
            return {"ok": False, "error": result["error"]}
    finally:
        await client.close()

    # Delete existing keys
    existing_result = await db.execute(select(ApiKey).where(ApiKey.exchange == "coinbase"))
    existing = existing_result.scalar_one_or_none()
    if existing:
        await db.delete(existing)

    # Save encrypted
    key = ApiKey(
        exchange="coinbase",
        api_key_enc=encrypt(data.api_key),
        api_secret_enc=encrypt(data.api_secret),
        is_valid=True,
    )
    db.add(key)
    await db.commit()

    # Auto-switch to LIVE mode and persist
    from bot.system_config import set_config
    settings.paper_mode = False
    await set_config("paper_mode", "false")
    await init_exchange(data.api_key, data.api_secret)

    return {"ok": True, "paper_mode": False}


@router.delete("/exchange")
async def delete_exchange_keys(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ApiKey).where(ApiKey.exchange == "coinbase"))
    existing = result.scalar_one_or_none()
    if existing:
        await db.delete(existing)
        await db.commit()

    await init_exchange()
    return {"ok": True}


@router.get("/symbols")
async def get_supported_symbols():
    return {"symbols": settings.supported_symbols}


@router.get("/mode")
async def get_mode():
    return {"paper_mode": settings.paper_mode}


@router.post("/mode")
async def toggle_mode(db: AsyncSession = Depends(get_db)):
    from bot.system_config import set_config

    settings.paper_mode = not settings.paper_mode

    # Reinitialize exchange client based on new mode
    api_key = ""
    api_secret = ""  # nosec B105 - placeholder for unset exchange credentials
    if not settings.paper_mode:
        key_result = await db.execute(
            select(ApiKey).where(ApiKey.exchange == "coinbase", ApiKey.is_valid.is_(True))
        )
        key = key_result.scalar_one_or_none()
        if key:
            api_key = decrypt(key.api_key_enc)
            api_secret = decrypt(key.api_secret_enc)
        else:
            settings.paper_mode = True
            await set_config("paper_mode", "true")
            return {
                "paper_mode": True,
                "error": "No hay API keys configuradas. Configura primero tus keys de Coinbase.",
            }

    # Persist mode to DB so it survives restarts
    await set_config("paper_mode", str(settings.paper_mode).lower())

    await init_exchange(api_key, api_secret)
    return {"paper_mode": settings.paper_mode}


@router.get("/notifications")
async def get_notification_settings():
    """Legacy endpoint: summary of enabled channels."""
    from bot.notifications.config import load_channel
    tg = await load_channel("telegram")
    email = await load_channel("email")
    return {
        "telegram": {
            "configured": bool(tg.get("bot_token")),
            "enabled": bool(tg.get("enabled")),
        },
        "email": {
            "configured": bool(email.get("smtp_host")),
            "enabled": bool(email.get("enabled")),
        },
    }
