import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.web.deps import get_db
from bot.models import StrategyConfig
from bot.engine.runner import start_strategy, stop_strategy, get_strategy_status, force_tick, STRATEGY_CLASSES

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


class StrategyUpdate(BaseModel):
    symbol: str = "BTC/USD"
    params: dict = {}


@router.get("")
async def list_strategies(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StrategyConfig))
    configs = result.scalars().all()

    strategies = []
    for name in STRATEGY_CLASSES:
        config = next((c for c in configs if c.name == name), None)
        status = get_strategy_status(name)
        strategies.append({
            "name": name,
            "symbol": config.symbol if config else "BTC/USD",
            "params": json.loads(config.params) if config else {},
            "is_active": config.is_active if config else False,
            "running": status is not None,
            "status": status,
        })
    return strategies


@router.get("/{name}")
async def get_strategy(name: str, db: AsyncSession = Depends(get_db)):
    if name not in STRATEGY_CLASSES:
        raise HTTPException(404, f"Strategy '{name}' not found")

    result = await db.execute(select(StrategyConfig).where(StrategyConfig.name == name))
    config = result.scalar_one_or_none()

    return {
        "name": name,
        "symbol": config.symbol if config else "BTC/USD",
        "params": json.loads(config.params) if config else {},
        "is_active": config.is_active if config else False,
        "running": get_strategy_status(name) is not None,
        "status": get_strategy_status(name),
    }


@router.put("/{name}")
async def update_strategy(name: str, data: StrategyUpdate, db: AsyncSession = Depends(get_db)):
    if name not in STRATEGY_CLASSES:
        raise HTTPException(404, f"Strategy '{name}' not found")

    result = await db.execute(select(StrategyConfig).where(StrategyConfig.name == name))
    config = result.scalar_one_or_none()

    # Validate params
    if name == "grid":
        p = data.params
        if p.get("lower_price", 0) >= p.get("upper_price", float("inf")):
            raise HTTPException(400, "Precio inferior debe ser menor que precio superior")
        if p.get("num_grids", 0) <= 0:
            raise HTTPException(400, "Numero de grids debe ser > 0")
        if p.get("amount_per_grid", 0) <= 0:
            raise HTTPException(400, "Cantidad por grid debe ser > 0")
    elif name == "dca":
        if data.params.get("amount_usd", 0) <= 0:
            raise HTTPException(400, "Monto por compra debe ser > 0")
        if data.params.get("interval_hours", 0) <= 0:
            raise HTTPException(400, "Intervalo debe ser > 0 horas")

    was_running = get_strategy_status(name) is not None

    if config:
        config.symbol = data.symbol
        config.params = json.dumps(data.params)
    else:
        config = StrategyConfig(
            name=name,
            symbol=data.symbol,
            params=json.dumps(data.params),
        )
        db.add(config)

    await db.commit()

    # If strategy is running, restart it to apply the new params
    restarted = False
    if was_running:
        await stop_strategy(name)
        if await start_strategy(name, data.symbol, data.params):
            config.is_active = True
            await db.commit()
            restarted = True

    return {"ok": True, "name": name, "restarted": restarted}


@router.post("/{name}/start")
async def start_strategy_endpoint(name: str, db: AsyncSession = Depends(get_db)):
    if name not in STRATEGY_CLASSES:
        raise HTTPException(404, f"Strategy '{name}' not found")

    result = await db.execute(select(StrategyConfig).where(StrategyConfig.name == name))
    config = result.scalar_one_or_none()

    if not config:
        raise HTTPException(400, f"Configure strategy '{name}' first")

    params = json.loads(config.params)
    ok = await start_strategy(name, config.symbol, params)
    if not ok:
        raise HTTPException(400, f"Strategy '{name}' is already running")

    config.is_active = True
    await db.commit()
    return {"ok": True, "name": name, "status": "started"}


@router.post("/{name}/tick")
async def force_strategy_tick(name: str):
    """Manually trigger a strategy tick (for testing/immediate execution)."""
    if name not in STRATEGY_CLASSES:
        raise HTTPException(404, f"Strategy '{name}' not found")
    return await force_tick(name)


@router.post("/{name}/stop")
async def stop_strategy_endpoint(name: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StrategyConfig).where(StrategyConfig.name == name))
    config = result.scalar_one_or_none()

    ok = await stop_strategy(name)
    if not ok:
        raise HTTPException(400, f"Strategy '{name}' is not running")

    if config:
        config.is_active = False
        await db.commit()
    return {"ok": True, "name": name, "status": "stopped"}
