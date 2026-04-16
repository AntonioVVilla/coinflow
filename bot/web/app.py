from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from bot.web.routes import (
    dashboard, strategies, trades, settings, webhook, auth, risk,
    notifications as notifs_route, websocket as ws_route, coinbase as cb_route,
    backtest as bt_route,
)
from bot.auth import require_auth

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="CryptoBot", version="1.0.0")

    # Public routes (no auth required)
    app.include_router(auth.router)

    # Protected routes
    deps = [Depends(require_auth)]
    app.include_router(dashboard.router, dependencies=deps)
    app.include_router(strategies.router, dependencies=deps)
    app.include_router(trades.router, dependencies=deps)
    app.include_router(settings.router, dependencies=deps)
    app.include_router(webhook.router)  # Webhook stays open (has passphrase)
    app.include_router(risk.router, dependencies=deps)
    app.include_router(notifs_route.router, dependencies=deps)
    app.include_router(cb_route.router, dependencies=deps)
    app.include_router(bt_route.router, dependencies=deps)
    app.include_router(ws_route.router)  # WebSocket

    # Health check
    @app.get("/api/health")
    async def health():
        return {"status": "ok"}

    # Static files (frontend)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index():
        return FileResponse(str(STATIC_DIR / "index.html"))

    return app
