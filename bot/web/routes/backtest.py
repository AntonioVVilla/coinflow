from fastapi import APIRouter
from pydantic import BaseModel
from bot.engine.backtest import run_backtest

router = APIRouter(prefix="/api/backtest", tags=["backtest"])


class BacktestRequest(BaseModel):
    strategy: str           # "grid" or "dca"
    symbol: str = "BTC/USD"
    params: dict = {}
    initial_quote: float = 1000.0
    timeframe: str = "1h"   # 5m, 15m, 1h, 4h, 1d
    candles: int = 500


@router.post("/run")
async def run(req: BacktestRequest):
    return await run_backtest(
        strategy_name=req.strategy,
        symbol=req.symbol,
        params=req.params,
        initial_quote=req.initial_quote,
        timeframe=req.timeframe,
        candles=req.candles,
    )
