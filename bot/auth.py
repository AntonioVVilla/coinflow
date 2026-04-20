import hashlib
import hmac
import logging
import secrets
import time
from typing import Optional

from fastapi import Cookie, HTTPException, Request
from sqlalchemy import select
from bot.database import async_session
from bot.models import AuthConfig

# In-memory session store: token -> expires_at (unix timestamp)
_sessions: dict[str, float] = {}
SESSION_TTL = 24 * 3600  # 24 hours
MAX_ATTEMPTS = 5
LOCKOUT_MINUTES = 15


def hash_password(password: str, salt: str | None = None) -> str:
    """Hash a password with PBKDF2."""
    if salt is None:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}${key.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, _ = stored.split("$", 1)
    return hmac.compare_digest(stored, hash_password(password, salt))


async def get_auth_config() -> Optional[AuthConfig]:
    async with async_session() as session:
        result = await session.execute(select(AuthConfig).limit(1))
        return result.scalar_one_or_none()


async def is_auth_enabled() -> bool:
    config = await get_auth_config()
    return bool(config and config.enabled)


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    _sessions[token] = time.time() + SESSION_TTL
    # Cleanup expired sessions
    now = time.time()
    for t in list(_sessions.keys()):
        if _sessions[t] < now:
            del _sessions[t]
    return token


def validate_session(token: str | None) -> bool:
    if not token:
        return False
    expires = _sessions.get(token)
    if not expires:
        return False
    if expires < time.time():
        del _sessions[token]
        return False
    return True


def destroy_session(token: str | None):
    if token and token in _sessions:
        del _sessions[token]


async def cleanup_expired_sessions():
    """Remove expired sessions. Called periodically by scheduler."""
    now = time.time()
    expired = [t for t, exp in _sessions.items() if exp < now]
    for t in expired:
        del _sessions[t]
    if expired:
        logging.getLogger(__name__).debug(f"Cleaned {len(expired)} expired sessions")


async def require_auth(
    request: Request,
    session_token: str | None = Cookie(default=None),
):
    """Dependency to protect routes. If auth is disabled, pass through."""
    # Health check and login endpoints are public
    path = request.url.path
    public = ("/api/health", "/api/auth/login", "/api/auth/status")
    if any(path.startswith(p) for p in public):
        return True

    if not await is_auth_enabled():
        return True

    if not validate_session(session_token):
        raise HTTPException(status_code=401, detail="No autenticado")
    return True
