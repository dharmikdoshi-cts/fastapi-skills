"""Reference security tests covering JWT + password + scopes."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from jose import jwt

from ..examples.security import (
    create_access_token,
    decode_token,
    hash_password,
    require_scopes,
    verify_password,
)


# ---- Password ----------------------------------------------------------

def test_hash_then_verify_round_trip():
    hashed = hash_password("hunter2!hunter2")
    assert hashed != "hunter2!hunter2"
    assert verify_password("hunter2!hunter2", hashed)


def test_verify_rejects_wrong_password():
    hashed = hash_password("correct")
    assert not verify_password("incorrect", hashed)


def test_hash_is_salted():
    a = hash_password("same-password")
    b = hash_password("same-password")
    assert a != b  # bcrypt salts each call


# ---- Access token ------------------------------------------------------

def test_access_token_round_trip():
    token = create_access_token(subject="user:42", scopes=["users:read"])
    payload = decode_token(token)
    assert payload["sub"] == "user:42"
    assert payload["type"] == "access"
    assert "users:read" in payload["scopes"]


def test_decode_rejects_tampered_signature(monkeypatch):
    token = create_access_token(subject="user:42")
    parts = token.split(".")
    tampered = ".".join([parts[0], parts[1], "deadbeef"])
    with pytest.raises(HTTPException) as exc:
        decode_token(tampered)
    assert exc.value.status_code == 401


def test_decode_rejects_expired_token():
    from app.config.settings import settings

    payload = {
        "sub": "user:1",
        "iat": int((datetime.now(UTC) - timedelta(hours=2)).timestamp()),
        "exp": int((datetime.now(UTC) - timedelta(hours=1)).timestamp()),
        "type": "access",
    }
    expired = jwt.encode(
        payload,
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(HTTPException) as exc:
        decode_token(expired)
    assert exc.value.status_code == 401


# ---- Scope guard -------------------------------------------------------

def test_require_scopes_passes_when_granted():
    guard = require_scopes("invoices:write")
    user = {"sub": "u:1", "scopes": ["invoices:read", "invoices:write"]}
    assert guard(user=user) is user


def test_require_scopes_rejects_when_missing():
    guard = require_scopes("invoices:write")
    user = {"sub": "u:1", "scopes": ["invoices:read"]}
    with pytest.raises(HTTPException) as exc:
        guard(user=user)
    assert exc.value.status_code == 403
