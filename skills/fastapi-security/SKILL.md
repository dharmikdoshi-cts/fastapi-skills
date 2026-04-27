---
name: fastapi-security
description: >
  Implement security patterns for FastAPI including JWT authentication with
  access/refresh tokens, password hashing with bcrypt, role-based access
  control (RBAC), CORS configuration, security headers middleware, rate
  limiting with Redis, and input sanitization. Use this skill whenever the
  user asks about authentication, authorization, JWT tokens, login/register,
  password hashing, CORS, rate limiting, security headers, RBAC, or
  protecting endpoints. Also trigger for "auth middleware", "bearer token",
  "refresh token", "password validation", or "API key auth". Python 3.12+,
  Annotated DI, FE-friendly error responses.
---

# FastAPI Security Skill

JWT auth, RBAC, CORS, rate limiting, security headers. Python 3.12+, Annotated DI.

---

## JWT Token Creation & Verification

```python
# core/security.py
from datetime import datetime, timedelta, timezone
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, Security
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.settings import settings
from app.config.database import get_db
from app.core.exceptions import UnauthorizedError, ForbiddenError
from app.models.User import User
from app.repositories.UserRepository import UserRepository

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer()


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(subject: int, extra: dict[str, Any] | None = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    claims = {"sub": str(subject), "exp": expire, "type": "access"}
    if extra:
        claims.update(extra)
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(subject: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    claims = {"sub": str(subject), "exp": expire, "type": "refresh"}
    return jwt.encode(claims, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str, token_type: str = "access") -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        if payload.get("type") != token_type:
            raise JWTError("Invalid token type")
        return payload
    except JWTError:
        raise UnauthorizedError("Invalid or expired token")
```

---

## Annotated Auth Dependencies

```python
# core/security.py (continued)
from typing import Annotated


async def get_current_user_from_token(
    credentials: HTTPAuthorizationCredentials = Security(security_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = verify_token(credentials.credentials, token_type="access")
    user_id = int(payload["sub"])
    user = await UserRepository(db).get_by_id(user_id)

    if not user:
        raise UnauthorizedError("User not found")
    if not user.is_active:
        raise UnauthorizedError("Account deactivated")
    return user


async def require_admin(
    user: User = Depends(get_current_user_from_token),
) -> User:
    if not user.is_admin:
        raise ForbiddenError("Admin access required")
    return user


# Type aliases for endpoints
CurrentUser = Annotated[User, Depends(get_current_user_from_token)]
AdminUser = Annotated[User, Depends(require_admin)]
```

Usage in endpoints:

```python
@router.get("/me")
async def get_me(user: CurrentUser):
    return StandardResponse(data=user)

@router.delete("/users/{id}")
async def delete_user(id: int, admin: AdminUser, service: UserServiceDep):
    await service.delete_user(id)
    return StandardResponse(message="User deleted")
```

---

## Auth Endpoints

```python
# api/v1/endpoints/auth.py
from fastapi import APIRouter
from app.api.dependencies import DbSession
from app.core.security import verify_password, hash_password, create_access_token, create_refresh_token
from app.core.exceptions import UnauthorizedError, ConflictError
from app.schemas.AuthSchema import LoginRequest, RegisterRequest, TokenResponse
from app.schemas.common import StandardResponse
from app.repositories.UserRepository import UserRepository

router = APIRouter()


@router.post("/register", response_model=StandardResponse[TokenResponse], status_code=201)
async def register(data: RegisterRequest, db: DbSession):
    repo = UserRepository(db)
    if await repo.get_by_email(data.email):
        raise ConflictError("User", data.email)

    user = await repo.create({
        "email": data.email,
        "full_name": data.full_name,
        "hashed_password": hash_password(data.password),
    })
    tokens = TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )
    return StandardResponse(code=201, data=tokens, message="Registration successful")


@router.post("/login", response_model=StandardResponse[TokenResponse])
async def login(data: LoginRequest, db: DbSession):
    repo = UserRepository(db)
    user = await repo.get_by_email(data.email)
    if not user or not verify_password(data.password, user.hashed_password):
        raise UnauthorizedError("Invalid email or password")

    tokens = TokenResponse(
        access_token=create_access_token(user.id),
        refresh_token=create_refresh_token(user.id),
    )
    return StandardResponse(data=tokens, message="Login successful")
```

### Auth Schemas

```python
# schemas/AuthSchema.py
from pydantic import BaseModel, EmailStr, Field, field_validator


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=128)

    @field_validator("password")
    @classmethod
    def strong_password(cls, v: str) -> str:
        if not any(c.isupper() for c in v):
            raise ValueError("Must contain at least one uppercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Must contain at least one digit")
        return v


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
```

---

## CORS Configuration

```python
# main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,  # never ["*"] in production
    allow_credentials=True,
    allow_methods=settings.ALLOWED_METHODS,
    allow_headers=settings.ALLOWED_HEADERS,
)
```

---

## Security Headers Middleware

```python
# core/middleware.py
from starlette.middleware.base import BaseHTTPMiddleware


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response
```

---

## Rate Limiting (Redis)

```python
# core/rate_limit.py
from typing import Annotated
from fastapi import Depends, Request
from redis.asyncio import Redis
from app.config.settings import settings
from app.core.exceptions import RateLimitError

redis_client = Redis.from_url(settings.REDIS_URL)


def rate_limit(limit: int = 100, window: int = 60):
    async def _limiter(request: Request):
        key = f"rl:{request.client.host}:{request.url.path}"
        current = await redis_client.incr(key)
        if current == 1:
            await redis_client.expire(key, window)
        if current > limit:
            raise RateLimitError()
    return _limiter

# Usage:
@router.post("/login", dependencies=[Depends(rate_limit(limit=10, window=60))])
async def login(...): ...

@router.post("/forgot-password", dependencies=[Depends(rate_limit(limit=3, window=300))])
async def forgot_password(...): ...
```

---

## Quick Checklist

- [ ] JWT with `HS256`, strong SECRET_KEY
- [ ] Access tokens: 30 min, refresh tokens: 7 days
- [ ] Passwords hashed with bcrypt, never stored plain
- [ ] `CurrentUser` and `AdminUser` Annotated aliases
- [ ] Password strength validation (length, uppercase, digit)
- [ ] CORS: explicit origins, no wildcards in production
- [ ] Security headers middleware
- [ ] Rate limiting on auth endpoints (Redis)
- [ ] All auth errors return FE-friendly format

---

## Examples in this skill

- [examples/security.py](examples/security.py) — bcrypt hashing, access/refresh JWT issue + decode, scope guard
- [examples/rate_limit.py](examples/rate_limit.py) — Redis sliding-window rate limiter (login + general API)
- [tests/test_security_example.py](tests/test_security_example.py) — password round-trip, expired/tampered token rejection, scope enforcement