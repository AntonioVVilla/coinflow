from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi import _rate_limit_exceeded_handler

from bot.web.rate_limit import limiter
from bot.web.routes import (
    dashboard, strategies, trades, settings, webhook, auth, risk,
    notifications as notifs_route, websocket as ws_route, coinbase as cb_route,
    backtest as bt_route, metrics as metrics_route,
)
from bot.auth import require_auth

STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    app = FastAPI(title="CryptoBot", version="1.0.0")

    # Rate limiting: hook slowapi into FastAPI so decorated endpoints enforce
    # their per-IP quotas and rejected requests become HTTP 429 responses.
    app.state.limiter = limiter
    # slowapi's handler signature is narrower than Starlette's generic one;
    # the cast keeps mypy happy without changing behaviour.
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
    app.add_middleware(SlowAPIMiddleware)

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
    app.include_router(metrics_route.router, dependencies=deps)
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
