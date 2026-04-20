import asyncio
import json
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from bot.engine.runner import get_exchange_client, get_all_statuses
from bot.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

# Active WebSocket connections
_connections: set[WebSocket] = set()


async def broadcast(event_type: str, payload: dict):
    """Send an event to all connected clients."""
    if not _connections:
        return
    message = json.dumps({"type": event_type, "data": payload})
    dead = set()
    for ws in list(_connections):  # iterate copy to avoid mutation issues
        try:
            await ws.send_text(message)
        except Exception as e:
            logger.debug(f"WS send failed: {e}")
            dead.add(ws)
    if dead:
        _connections.difference_update(dead)
        logger.info(f"Removed {len(dead)} dead WS connection(s). Active: {len(_connections)}")


async def _price_streamer():
    """Background task that streams live prices to all connected clients."""
    while True:
        try:
            if _connections:
                client = get_exchange_client()
                if client:
                    prices = {}
                    for symbol in settings.supported_symbols:
                        try:
                            ticker = await client.fetch_ticker(symbol)
                            prices[symbol] = ticker.last
                        except Exception as ticker_err:
                            logger.debug(f"Ticker fetch failed for {symbol}: {ticker_err}")
                    if prices:
                        await broadcast("prices", {
                            "prices": prices,
                            "strategies": get_all_statuses(),
                        })
        except Exception as e:
            logger.error(f"Price streamer error: {e}")
        await asyncio.sleep(3)  # every 3 seconds


def start_streamer():
    """Start the background streamer task."""
    asyncio.create_task(_price_streamer())


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    _connections.add(websocket)
    logger.info(f"WS client connected. Total: {len(_connections)}")
    try:
        while True:
            # Keep connection alive, ignore any client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(websocket)
        logger.info(f"WS client disconnected. Total: {len(_connections)}")
