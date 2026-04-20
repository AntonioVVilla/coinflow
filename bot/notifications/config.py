"""Load/save notification channel configs from DB with encryption."""
import json
from sqlalchemy import select
from bot.database import async_session
from bot.models import NotificationSetting
from bot.security import encrypt, decrypt


async def load_channel(channel: str) -> dict:
    """Returns {enabled, ...config fields} or {enabled: False}."""
    async with async_session() as session:
        result = await session.execute(
            select(NotificationSetting).where(NotificationSetting.channel == channel)
        )
        row = result.scalar_one_or_none()
    if not row:
        return {"enabled": False}
    config: dict = {}
    try:
        if row.config_enc:
            config = json.loads(decrypt(row.config_enc))
    except Exception:
        config = {}
    config["enabled"] = row.is_enabled
    return config


async def save_channel(channel: str, enabled: bool, config: dict) -> None:
    """Save config for a channel. Encrypts sensitive data."""
    encrypted = encrypt(json.dumps(config)) if config else ""
    async with async_session() as session:
        result = await session.execute(
            select(NotificationSetting).where(NotificationSetting.channel == channel)
        )
        row = result.scalar_one_or_none()
        if not row:
            row = NotificationSetting(channel=channel, config_enc=encrypted, is_enabled=enabled)
            session.add(row)
        else:
            row.config_enc = encrypted
            row.is_enabled = enabled
        await session.commit()


async def delete_channel(channel: str) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(NotificationSetting).where(NotificationSetting.channel == channel)
        )
        row = result.scalar_one_or_none()
        if row:
            await session.delete(row)
            await session.commit()
