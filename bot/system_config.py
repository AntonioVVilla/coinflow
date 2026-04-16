"""Persistent key-value system config stored in DB."""
from sqlalchemy import select
from bot.database import async_session
from bot.models import SystemConfig


async def get_config(key: str, default: str = "") -> str:
    async with async_session() as session:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        row = result.scalar_one_or_none()
        return row.value if row else default


async def set_config(key: str, value: str) -> None:
    async with async_session() as session:
        result = await session.execute(
            select(SystemConfig).where(SystemConfig.key == key)
        )
        row = result.scalar_one_or_none()
        if row:
            row.value = value
        else:
            session.add(SystemConfig(key=key, value=value))
        await session.commit()


async def get_bool(key: str, default: bool = False) -> bool:
    val = await get_config(key, str(default).lower())
    return val.lower() in ("true", "1", "yes")
