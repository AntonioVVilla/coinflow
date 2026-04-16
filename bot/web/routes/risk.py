from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.web.deps import get_db
from bot.models import RiskConfig
from bot.engine.runner import kill_switch

router = APIRouter(prefix="/api/risk", tags=["risk"])


class RiskSettings(BaseModel):
    enabled: bool = False
    max_daily_loss_usd: float = 0
    max_drawdown_pct: float = 0
    max_btc_allocation_pct: float = 100
    max_eth_allocation_pct: float = 100
    circuit_breaker_pct: float = 0


@router.get("")
async def get_risk(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RiskConfig).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        return {
            "enabled": False,
            "max_daily_loss_usd": 0,
            "max_drawdown_pct": 0,
            "max_btc_allocation_pct": 100,
            "max_eth_allocation_pct": 100,
            "circuit_breaker_pct": 0,
            "daily_reference_usd": 0,
            "paused_until": None,
        }
    return {
        "enabled": config.enabled,
        "max_daily_loss_usd": config.max_daily_loss_usd,
        "max_drawdown_pct": config.max_drawdown_pct,
        "max_btc_allocation_pct": config.max_btc_allocation_pct,
        "max_eth_allocation_pct": config.max_eth_allocation_pct,
        "circuit_breaker_pct": config.circuit_breaker_pct,
        "daily_reference_usd": config.daily_reference_usd,
        "paused_until": config.paused_until.isoformat() if config.paused_until else None,
    }


@router.put("")
async def update_risk(data: RiskSettings, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(RiskConfig).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        config = RiskConfig()
        db.add(config)

    config.enabled = data.enabled
    config.max_daily_loss_usd = data.max_daily_loss_usd
    config.max_drawdown_pct = data.max_drawdown_pct
    config.max_btc_allocation_pct = data.max_btc_allocation_pct
    config.max_eth_allocation_pct = data.max_eth_allocation_pct
    config.circuit_breaker_pct = data.circuit_breaker_pct

    # Reset daily reference when enabling
    if data.enabled and (not config.daily_reference_at
                         or config.daily_reference_at.date() < datetime.now(timezone.utc).date()):
        # Will be set on next pre-trade check
        pass

    await db.commit()
    return {"ok": True}


@router.post("/resume")
async def resume_trading(db: AsyncSession = Depends(get_db)):
    """Manually resume trading after circuit breaker."""
    result = await db.execute(select(RiskConfig).limit(1))
    config = result.scalar_one_or_none()
    if config:
        config.paused_until = None
        await db.commit()
    return {"ok": True}


@router.post("/kill-switch")
async def trigger_kill_switch():
    """EMERGENCY: Stop all strategies and cancel open orders."""
    result = await kill_switch()
    return result
