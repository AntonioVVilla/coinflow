"""Tests for authentication and sessions."""
import time
import pytest
from bot.auth import (
    create_session,
    validate_session,
    destroy_session,
    hash_password,
    verify_password,
    require_auth,
    SESSION_TTL,
)


def test_create_session_generates_token():
    token = create_session()
    assert isinstance(token, str)
    assert len(token) > 20
    assert token not in ("", None)


def test_validate_session_accepts_valid_token():
    token = create_session()
    assert validate_session(token) is True


def test_validate_session_rejects_invalid_token():
    assert validate_session("invalid-token-xyz") is False
    assert validate_session("") is False
    assert validate_session(None) is False


def test_destroy_session_removes_token():
    token = create_session()
    assert validate_session(token) is True
    destroy_session(token)
    assert validate_session(token) is False


def test_validate_session_rejects_expired_token(monkeypatch):
    """Test that expired sessions are rejected."""
    fake_time = 1000000
    monkeypatch.setattr(time, "time", lambda: fake_time)

    token = create_session()

    monkeypatch.setattr(time, "time", lambda: fake_time + SESSION_TTL + 1)
    assert validate_session(token) is False


def test_hash_password_verify_roundtrip():
    pw = "test-password-123"
    hashed = hash_password(pw)
    assert hashed != pw
    assert "$" in hashed
    assert verify_password(pw, hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_verify_password_handles_empty():
    assert verify_password("test", "") is False


def test_verify_password_handles_no_dollar():
    assert verify_password("test", "no-dollar-sign") is False


@pytest.mark.asyncio
async def test_require_auth_passes_for_public_endpoints():
    from fastapi import Request
    from unittest.mock import MagicMock

    request = MagicMock(spec=Request)
    request.url.path = "/api/health"

    result = await require_auth(request, session_token=None)
    assert result is True


@pytest.mark.asyncio
async def test_require_auth_rejects_protected_without_session(monkeypatch):
    from fastapi import Request, HTTPException
    from unittest.mock import MagicMock, AsyncMock

    request = MagicMock(spec=Request)
    request.url.path = "/api/dashboard"

    import bot.auth as auth_module
    auth_module._sessions.clear()

    # Use monkeypatch so the replacement is rolled back at teardown; otherwise
    # `is_auth_enabled` stays stubbed and later tests that hit protected
    # endpoints unexpectedly receive 401.
    monkeypatch.setattr(auth_module, "is_auth_enabled", AsyncMock(return_value=True))

    try:
        await require_auth(request, session_token="invalid-token")
    except HTTPException as exc:
        assert exc.status_code == 401