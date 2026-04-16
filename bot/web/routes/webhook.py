from fastapi import APIRouter, Request, HTTPException
from bot.engine.runner import get_webhook_strategy, get_exchange_client, _execute_orders

router = APIRouter(prefix="/api/webhook", tags=["webhook"])


@router.post("/tradingview")
async def tradingview_webhook(request: Request):
    strategy = get_webhook_strategy()
    if not strategy:
        raise HTTPException(400, "Webhook strategy is not active")

    client = get_exchange_client()
    if not client:
        raise HTTPException(500, "Exchange client not initialized")

    try:
        signal = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body")

    # Get current price for amount calculation
    symbol = signal.get("symbol", strategy.symbol)
    ticker = await client.fetch_ticker(symbol)

    order = strategy.execute_signal(signal, ticker.last)
    if not order:
        raise HTTPException(400, "Signal rejected (invalid passphrase or action)")

    await _execute_orders("webhook", [order])
    return {"ok": True, "action": order.side, "symbol": order.symbol, "amount": order.amount}
