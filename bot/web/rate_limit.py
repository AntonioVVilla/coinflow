"""Shared slowapi limiter for the FastAPI app.

Kept in a dedicated module so multiple routers can import the same limiter
instance (slowapi stores per-key counters on the limiter object, so a second
`Limiter(...)` call would reset them).

Endpoints protected today:
    - /api/auth/login         5 req/min/IP   (brute-force on the password)
    - /api/auth/setup         3 req/min/IP   (first-time or rotation)
    - /api/auth/disable       3 req/min/IP
    - /api/webhook/tradingview 30 req/min/IP (TradingView bursts)
"""
from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
