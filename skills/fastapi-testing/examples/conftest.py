"""Reusable pytest fixtures for an async FastAPI + SQLAlchemy project.

Drop into `tests/conftest.py` and adapt imports.

Provides:
  - `engine`         : session-scoped async engine pointed at a test DB
  - `db_schema`      : creates tables once per session (or use Alembic)
  - `session`        : function-scoped AsyncSession with rollback isolation
  - `app`            : FastAPI app with DB session dependency overridden
  - `client`         : httpx AsyncClient bound to the app
  - `auth_client`    : same client with a known user injected
  - `make_user`      : factory that inserts a user via the session
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.database import Base, get_session
from app.main import app as fastapi_app
from app.models.user import User
from app.security.auth import get_current_user

TEST_DATABASE_URL = "postgresql+asyncpg://erp:erp@localhost:5432/erp_test"


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, future=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def db_schema(engine: AsyncEngine) -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    """Function-scoped session that rolls back at end of test."""
    connection = await engine.connect()
    transaction = await connection.begin()
    factory = async_sessionmaker(bind=connection, expire_on_commit=False, class_=AsyncSession)
    sess = factory()
    try:
        yield sess
    finally:
        await sess.close()
        await transaction.rollback()
        await connection.close()


@pytest_asyncio.fixture
async def app(session: AsyncSession):
    async def _override_session() -> AsyncIterator[AsyncSession]:
        yield session

    fastapi_app.dependency_overrides[get_session] = _override_session
    yield fastapi_app
    fastapi_app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.fixture
def make_user(session: AsyncSession) -> Callable[..., User]:
    counter = {"i": 0}

    async def _make(**kwargs) -> User:
        counter["i"] += 1
        defaults = {
            "email": f"u{counter['i']}@example.com",
            "name": f"User {counter['i']}",
            "is_active": True,
        }
        user = User(**(defaults | kwargs))
        session.add(user)
        await session.flush()
        return user

    return _make  # type: ignore[return-value]


@pytest_asyncio.fixture
async def auth_client(app, make_user) -> AsyncIterator[AsyncClient]:
    user = await make_user(email="auth@test.com")

    async def _override_current_user() -> User:
        return user

    app.dependency_overrides[get_current_user] = _override_current_user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        c.headers["X-Test-User-Id"] = str(user.id)
        yield c
