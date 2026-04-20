from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Response, Cookie
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from bot.web.deps import get_db
from bot.models import AuthConfig
from bot.auth import (
    hash_password, verify_password, create_session, destroy_session,
    validate_session, is_auth_enabled, MAX_ATTEMPTS, LOCKOUT_MINUTES,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginData(BaseModel):
    password: str


class SetupData(BaseModel):
    password: str
    current_password: str = ""  # required when changing existing password


@router.get("/status")
async def auth_status(session_token: str | None = Cookie(default=None)):
    enabled = await is_auth_enabled()
    authenticated = validate_session(session_token) if enabled else True
    return {"enabled": enabled, "authenticated": authenticated}


@router.post("/setup")
async def setup_password(data: SetupData, db: AsyncSession = Depends(get_db),
                         session_token: str | None = Cookie(default=None)):
    """Set initial password or change existing one."""
    if len(data.password) < 12:
        raise HTTPException(400, "El password debe tener al menos 12 caracteres")

    result = await db.execute(select(AuthConfig).limit(1))
    config = result.scalar_one_or_none()

    if config and config.enabled:
        # Changing password requires being authenticated or knowing current
        if not validate_session(session_token):
            if not verify_password(data.current_password, config.password_hash):
                raise HTTPException(401, "Password actual incorrecto")

    if not config:
        config = AuthConfig(enabled=True, password_hash=hash_password(data.password))
        db.add(config)
    else:
        config.password_hash = hash_password(data.password)
        config.enabled = True
        config.failed_attempts = 0
        config.locked_until = None

    await db.commit()
    return {"ok": True}


@router.post("/disable")
async def disable_auth(data: LoginData, db: AsyncSession = Depends(get_db)):
    """Remove password protection. Requires current password."""
    result = await db.execute(select(AuthConfig).limit(1))
    config = result.scalar_one_or_none()
    if not config:
        return {"ok": True}

    if not verify_password(data.password, config.password_hash):
        raise HTTPException(401, "Password incorrecto")

    config.enabled = False
    config.password_hash = ""  # nosec B105 - clearing stored hash, not a password literal
    await db.commit()
    return {"ok": True}


@router.post("/login")
async def login(data: LoginData, response: Response, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AuthConfig).limit(1))
    config = result.scalar_one_or_none()

    if not config or not config.enabled:
        raise HTTPException(400, "Autenticacion no esta habilitada")

    now = datetime.now(timezone.utc)
    if config.locked_until and config.locked_until > now:
        remaining = int((config.locked_until - now).total_seconds() / 60) + 1
        raise HTTPException(
            429, f"Cuenta bloqueada. Intenta de nuevo en {remaining} minutos."
        )

    if not verify_password(data.password, config.password_hash):
        config.failed_attempts = (config.failed_attempts or 0) + 1
        if config.failed_attempts >= MAX_ATTEMPTS:
            config.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            config.failed_attempts = 0
        await db.commit()
        raise HTTPException(401, "Password incorrecto")

    # Success
    config.failed_attempts = 0
    config.locked_until = None
    await db.commit()

    token = create_session()
    response.set_cookie(
        "session_token", token,
        httponly=True, max_age=86400, samesite="lax",
    )
    return {"ok": True}


@router.post("/logout")
async def logout(response: Response, session_token: str | None = Cookie(default=None)):
    destroy_session(session_token)
    response.delete_cookie("session_token")
    return {"ok": True}
