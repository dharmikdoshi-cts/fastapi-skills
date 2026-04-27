"""Reference JWT + password hashing module. Drop into app/security/security.py."""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config.settings import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ---- Password ----------------------------------------------------------

def hash_password(plain: str) -> str:
    return pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_ctx.verify(plain, hashed)


# ---- Tokens ------------------------------------------------------------

def create_access_token(*, subject: str, scopes: list[str] | None = None) -> str:
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.ACCESS_TOKEN_TTL_MINUTES)).timestamp()),
        "type": "access",
        "scopes": scopes or [],
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def create_refresh_token(*, subject: str, jti: str) -> str:
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=settings.REFRESH_TOKEN_TTL_DAYS)).timestamp()),
        "type": "refresh",
    }
    return jwt.encode(
        payload,
        settings.JWT_SECRET.get_secret_value(),
        algorithm=settings.JWT_ALGORITHM,
    )


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(
            token,
            settings.JWT_SECRET.get_secret_value(),
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token") from e


# ---- Dependency --------------------------------------------------------

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Trimmed example. In real code, fetch user from DB by sub."""
    payload = decode_token(token)
    if payload.get("type") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token type")
    return payload  # replace with actual User lookup


def require_scopes(*required: str):
    def _dep(user=Depends(get_current_user)):
        granted = set(user.get("scopes", []))
        if not set(required).issubset(granted):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Missing scope")
        return user

    return _dep
