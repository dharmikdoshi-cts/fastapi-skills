---
name: fastapi-simple
description: >
  Generate a simple/flat FastAPI project structure for small-to-medium APIs
  (under 50 endpoints, 1-4 developers, single business domain, MVPs, prototypes).
  Use this skill whenever the user asks to scaffold, create, or generate a
  FastAPI project and the scope is small. Keywords: "simple API", "quick backend",
  "MVP", "prototype", "small project", "REST API", "CRUD API". Also trigger when
  the user says "FastAPI project" without specifying scale — default to simple.
  Uses Poetry, Python 3.12+, Ruff, Annotated dependencies, Protocol-based repos,
  and FE-friendly standardized responses. Do NOT use for large-scale or
  multi-domain projects — use fastapi-modular instead.
---

# FastAPI Simple Structure Skill

Production-ready FastAPI project with a flat directory layout.
Poetry + Python 3.12+ | Ruff | Annotated DI | Protocol repos | FE-friendly responses

---

## Decision Check

Use this skill when **all** are true:
- Under 50 API endpoints
- 1-4 developers
- Single business domain
- Fast delivery / MVP focus

If larger, use **fastapi-modular** skill instead.

---

## Directory Layout

```
project_root/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app + lifespan
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py             # Pydantic BaseSettings + SettingsConfigDict
│   │   └── database.py             # Async SQLAlchemy engine + session
│   ├── api/
│   │   ├── __init__.py
│   │   ├── dependencies.py         # Annotated type aliases for DI
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── router.py           # Aggregates all v1 endpoint routers
│   │       └── endpoints/
│   │           ├── __init__.py
│   │           ├── auth.py
│   │           ├── users.py
│   │           ├── items.py
│   │           └── health.py       # /health, /health/db, /ready
│   ├── core/
│   │   ├── __init__.py
│   │   ├── security.py             # JWT creation/verification, password hashing
│   │   ├── exceptions.py           # Custom exceptions + global handlers
│   │   └── middleware.py           # RequestID, logging, security headers
│   ├── models/
│   │   ├── __init__.py
│   │   ├── base.py                 # Base, TimestampMixin, SoftDeleteMixin
│   │   ├── User.py                 # class User(Base)
│   │   └── Item.py                 # class Item(Base)
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── common.py               # StandardResponse, PaginatedResponse
│   │   ├── UserSchema.py           # UserCreate, UserUpdate, UserResponse
│   │   ├── ItemSchema.py
│   │   └── AuthSchema.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── UserService.py          # Depends on UserRepositoryProtocol
│   │   └── ItemService.py
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── protocols.py            # Repository Protocol interfaces
│   │   ├── base.py                 # BaseAsyncRepository (generic CRUD)
│   │   ├── UserRepository.py
│   │   └── ItemRepository.py
│   └── utils/
│       ├── __init__.py
│       ├── logger.py               # Structured JSON logger
│       └── helpers.py
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── unit/
│   └── integration/
├── migrations/
│   ├── env.py                      # Async Alembic config
│   ├── script.py.mako
│   └── versions/
├── .env.example
├── pyproject.toml
├── Makefile
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

## File Naming Conventions

| Layer | File Name | Contains |
|-------|-----------|----------|
| Model | `User.py` | `class User` |
| Schema | `UserSchema.py` | `UserCreate`, `UserUpdate`, `UserResponse` |
| Service | `UserService.py` | `class UserService` |
| Repository | `UserRepository.py` | `class UserRepository` |
| Protocol | `protocols.py` | `UserRepositoryProtocol`, etc. |
| Endpoint | `users.py` | Router with `/users` endpoints |

Principle: **Class name = File name** (PascalCase for class files).

---

## Key File Templates

### app/main.py

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config.settings import settings
from app.config.database import engine
from app.api.v1.router import api_v1_router
from app.core.exceptions import register_exception_handlers
from app.core.middleware import RequestIDMiddleware, SecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify DB connection, warm caches, etc.
    yield
    # Shutdown: dispose engine, close Redis, cleanup
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=settings.DESCRIPTION,
    lifespan=lifespan,
)

# Middleware (order matters — outermost first)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=settings.ALLOWED_METHODS,
    allow_headers=settings.ALLOWED_HEADERS,
)

# Exception handlers
register_exception_handlers(app)

# Routers
app.include_router(api_v1_router, prefix="/api/v1")
```

### app/config/settings.py

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=True,
        extra="ignore",
    )

    PROJECT_NAME: str = "FastAPI Application"
    VERSION: str = "1.0.0"
    DESCRIPTION: str = ""
    DEBUG: bool = False

    # Database (async)
    DATABASE_URL: str  # postgresql+asyncpg://user:pass@host/db
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 30

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]
    ALLOWED_METHODS: list[str] = ["GET", "POST", "PUT", "DELETE"]
    ALLOWED_HEADERS: list[str] = ["*"]

    # Redis
    REDIS_URL: str = "redis://localhost:6379"

    # Logging
    LOG_LEVEL: str = "INFO"


settings = Settings()
```

### app/config/database.py

```python
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import settings

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### app/api/dependencies.py — Annotated Type Aliases

```python
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.config.database import get_db
from app.models.User import User
from app.repositories.UserRepository import UserRepository
from app.repositories.CachedUserRepository import CachedUserRepository
from app.services.UserService import UserService
from app.core.security import get_current_user_from_token

# Database session
DbSession = Annotated[AsyncSession, Depends(get_db)]

# Services (wire repo → service here)
def get_user_service(db: DbSession) -> UserService:
    repo = UserRepository(db)
    return UserService(repo)

UserServiceDep = Annotated[UserService, Depends(get_user_service)]

# Auth
CurrentUser = Annotated[User, Depends(get_current_user_from_token)]
```

### app/schemas/common.py — FE-Friendly Responses

```python
from typing import Any, Generic, TypeVar
from pydantic import BaseModel

T = TypeVar("T")


class FieldError(BaseModel):
    field: str
    message: str


class StandardResponse(BaseModel, Generic[T]):
    success: bool = True
    code: int = 200
    message: str = "Success"
    data: T | None = None
    errors: list[FieldError] | None = None


class PaginatedResponse(BaseModel, Generic[T]):
    success: bool = True
    code: int = 200
    message: str = "Success"
    data: list[T] = []
    errors: list[FieldError] | None = None
    total: int = 0
    page: int = 1
    page_size: int = 20
    total_pages: int = 0
```

### app/api/v1/endpoints/users.py — Endpoint Example

```python
from fastapi import APIRouter, Query, status

from app.api.dependencies import UserServiceDep, CurrentUser
from app.schemas.common import StandardResponse, PaginatedResponse
from app.schemas.UserSchema import UserCreate, UserResponse

router = APIRouter()


@router.post(
    "/",
    response_model=StandardResponse[UserResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_user(data: UserCreate, service: UserServiceDep):
    user = await service.create_user(data)
    return StandardResponse(
        code=201, data=user, message="User created successfully"
    )


@router.get("/", response_model=PaginatedResponse[UserResponse])
async def list_users(
    service: UserServiceDep,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    users, total = await service.get_paginated(page, page_size)
    return PaginatedResponse(
        data=users,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=(total + page_size - 1) // page_size,
    )


@router.get("/me", response_model=StandardResponse[UserResponse])
async def get_me(user: CurrentUser):
    return StandardResponse(data=user)
```

### app/api/v1/endpoints/health.py

```python
from fastapi import APIRouter
from sqlalchemy import text

from app.api.dependencies import DbSession

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "healthy"}


@router.get("/health/db")
async def health_db(db: DbSession):
    await db.execute(text("SELECT 1"))
    return {"status": "healthy", "database": "connected"}


@router.get("/ready")
async def readiness(db: DbSession):
    await db.execute(text("SELECT 1"))
    return {"status": "ready"}
```

### pyproject.toml (Poetry + Python 3.12 + Ruff)

```toml
[tool.poetry]
name = "my-fastapi-app"
version = "1.0.0"
description = "FastAPI application"
authors = ["Your Name <you@example.com>"]

[tool.poetry.dependencies]
python = "^3.12"
fastapi = {extras = ["standard"], version = "^0.115.0"}
sqlalchemy = {extras = ["asyncio"], version = "^2.0.0"}
alembic = "^1.13.0"
asyncpg = "^0.30.0"
pydantic-settings = "^2.5.0"
python-jose = {extras = ["cryptography"], version = "^3.3.0"}
passlib = {extras = ["bcrypt"], version = "^1.7.4"}
python-json-logger = "^3.0.0"
redis = "^5.0.0"

[tool.poetry.group.dev.dependencies]
ruff = "^0.8.0"
mypy = "^1.13.0"
pytest = "^8.3.0"
pytest-asyncio = "^0.24.0"
httpx = "^0.28.0"
aiosqlite = "^0.20.0"
pre-commit = "^4.0.0"

[tool.ruff]
target-version = "py312"
line-length = 88

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "N", "S", "RUF"]
ignore = ["S101"]  # allow assert in tests

[tool.ruff.lint.isort]
known-first-party = ["app"]

[tool.mypy]
python_version = "3.12"
strict = true

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short -x"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"
```

### Makefile

```makefile
.PHONY: install dev test lint format migrate

install:
    poetry install

dev:
    poetry run fastapi dev app/main.py

run:
    poetry run fastapi run app/main.py

test:
    poetry run pytest

lint:
    poetry run ruff check .
    poetry run mypy app

format:
    poetry run ruff format .
    poetry run ruff check --fix .

migrate:
    poetry run alembic upgrade head

migrate-create:
    poetry run alembic revision --autogenerate -m "$(name)"
```

### Dockerfile (Poetry + Python 3.12)

```dockerfile
FROM python:3.12-slim AS builder

WORKDIR /app
RUN pip install poetry && \
    poetry config virtualenvs.create false

COPY pyproject.toml poetry.lock ./
RUN poetry install --no-dev --no-interaction --no-ansi

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY . .

EXPOSE 8000
CMD ["fastapi", "run", "app/main.py", "--port", "8000"]
```

---

## Layered Architecture Rules

1. **Endpoints** → Accept HTTP, validate via Pydantic, call services, return `StandardResponse`
2. **Services** → Business logic only. Depend on Protocol, not concrete repos
3. **Repositories** → Data access only. Extend `BaseAsyncRepository`
4. **Models** → SQLAlchemy ORM. No logic beyond columns/relationships
5. **Schemas** → Pydantic models. Separate Create/Update/Response

Dependencies flow downward. Never skip layers.

---

## Quick Checklist

- [ ] Python 3.12+ syntax: `str | None`, `list[str]`, `dict[str, Any]`
- [ ] `Annotated[Type, Depends()]` aliases in `dependencies.py`
- [ ] `SettingsConfigDict` (not inner `class Config`)
- [ ] Lifespan context manager with real startup/shutdown
- [ ] Every endpoint returns `StandardResponse` or `PaginatedResponse`
- [ ] Validation errors return `errors: [{field, message}]` array
- [ ] Health endpoints: `/health`, `/health/db`, `/ready`
- [ ] Ruff for linting + formatting (no black/isort/flake8)
- [ ] `fastapi dev` / `fastapi run` commands
- [ ] Services depend on Protocol, not concrete repos
- [ ] Dockerfile uses multi-stage build with `python:3.12-slim`