---
name: fastapi-database
description: >
  Implement async database patterns for FastAPI including PostgreSQL with
  AsyncPG, async SQLAlchemy engine/session, BaseAsyncRepository with generic
  CRUD, Alembic async migrations with timestamp naming, connection pooling,
  and query optimization. Use this skill whenever the user asks about database
  setup, async database, SQLAlchemy async, Alembic migrations, repository
  pattern, database connection pooling, migration naming, or when setting up
  the data access layer. Also trigger for "asyncpg", "async session",
  "database config", "migration", or "repository pattern".
---

# FastAPI Database Skill

Async database configuration, repository patterns, and migration management.

---

## Async Engine + Session

```python
# config/database.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from app.config.settings import settings

engine = create_async_engine(
    settings.DATABASE_URL,          # postgresql+asyncpg://user:pass@host/db
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    pool_timeout=30,
    pool_recycle=1800,
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

Dispose engine in lifespan shutdown: `await engine.dispose()`

---

## Base Model with Mixins

```python
# models/base.py
from datetime import datetime
from sqlalchemy import Column, Integer, DateTime, Boolean, func
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


class SoftDeleteMixin:
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
```

### Model Example

```python
# models/user.py
from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship
from app.models.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(100), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)

    items = relationship("Item", back_populates="owner", lazy="selectin")
```

---

## BaseAsyncRepository

```python
# repositories/base.py
from typing import Generic, List, Optional, Type, TypeVar, Dict, Any
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

ModelType = TypeVar("ModelType")


class BaseAsyncRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self.session = session

    async def get_by_id(self, id: int) -> Optional[ModelType]:
        result = await self.session.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()

    async def get_all(self, skip: int = 0, limit: int = 100) -> List[ModelType]:
        result = await self.session.execute(
            select(self.model).offset(skip).limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, obj_data: Dict[str, Any]) -> ModelType:
        db_obj = self.model(**obj_data)
        self.session.add(db_obj)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def update(self, db_obj: ModelType, update_data: Dict[str, Any]) -> ModelType:
        for field, value in update_data.items():
            if value is not None:
                setattr(db_obj, field, value)
        await self.session.flush()
        await self.session.refresh(db_obj)
        return db_obj

    async def delete(self, db_obj: ModelType) -> None:
        await self.session.delete(db_obj)
        await self.session.flush()

    async def count(self, **filters) -> int:
        query = select(func.count()).select_from(self.model)
        for field, value in filters.items():
            query = query.where(getattr(self.model, field) == value)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def get_paginated(self, page: int = 1, page_size: int = 20) -> tuple[List[ModelType], int]:
        total = await self.count()
        result = await self.session.execute(
            select(self.model).offset((page - 1) * page_size).limit(page_size)
        )
        return list(result.scalars().all()), total
```

### Concrete Repository

```python
# repositories/user_repository.py
from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.user import User
from app.repositories.base import BaseAsyncRepository


class UserRepository(BaseAsyncRepository[User]):
    def __init__(self, session: AsyncSession):
        super().__init__(User, session)

    async def get_by_email(self, email: str) -> Optional[User]:
        result = await self.session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
```

---

## Alembic Async Migrations

### alembic.ini

```ini
[alembic]
script_location = migrations
# Filename pattern: ddmmyyyy_hhmmss_<slug>.py   (8-digit date + 6-digit time)
file_template = %%(day).2d%%(month).2d%%(year)d_%%(hour).2d%%(minute).2d%%(second).2d_%%(slug)s
timezone = UTC
truncate_slug_length = 40
```

Examples produced (note `yyyy` is 4 digits → 8-digit date total):

```
27042026_093045_create_users_table.py
27042026_093112_create_invoices_table.py
27042026_094008_add_email_index_to_users.py
```

**Format confirmed:** `DDMMYYYY_HHMMSS_<slug>.py` — that's `02 + 02 + 04 = 8` date digits, then `_`, then `HHMMSS = 6` time digits, then `_<slug>`.

**Caveat on sorting:** lexicographic sort of `ddmmyyyy` is wrong (`27042026` sorts before `28012025` even though Jan 28 2025 is earlier). Alembic itself relies on `down_revision` in each file, not filenames, so the chain is correct — but `ls`, diffs, and CI scripts that sort by name will list migrations out of chronological order. If that matters, switch to `yyyymmdd_hhmmss`.

---

### One migration per table (project convention)

Keep migrations **single-purpose** — one DDL change per file:

| Do | Don't |
|----|-------|
| `27042026_093045_create_users_table.py` | `27042026_093045_initial_schema.py` (10 tables in one) |
| `27042026_093112_create_invoices_table.py` | combining table + index + seed in one file |
| `27042026_094008_add_email_index_to_users.py` | mixing two unrelated alters |
| `27042026_094530_add_status_column_to_invoices.py` | |

**Why:**
- Reviewable diff — one table per PR-sized chunk.
- Targeted rollback — `alembic downgrade -1` reverts exactly one logical change.
- Conflict resolution — two devs adding two tables in parallel produce two files, not a merge conflict in one.
- Bisectable — when prod breaks, `git bisect` lands on a single intent.

**Slug rules:**
- `create_<table>_table` for new tables
- `add_<column>_to_<table>` / `drop_<column>_from_<table>` for column changes
- `add_<name>_index_to_<table>` for indexes
- `add_<name>_constraint_to_<table>` for constraints
- `backfill_<table>_<purpose>` for data-only migrations (separate from schema migrations)

**Generate migrations one table at a time:**

```bash
alembic revision --autogenerate -m "create users table"
# review file, ensure it touches only `users`
alembic revision --autogenerate -m "create invoices table"
# review again
```

If autogenerate emits multiple unrelated changes in one file, **split it manually** before committing.

### Async env.py

```python
# migrations/env.py
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool
from alembic import context
from app.config.settings import settings
from app.models.base import Base
from app.models.user import User  # noqa: F401 — needed for autogenerate
from app.models.item import Item  # noqa: F401

config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    run_migrations_online()
```

---

## Query Optimization

1. Use `selectin` loading: `relationship("Item", lazy="selectin")`
2. Explicit eager load: `select(User).options(selectinload(User.items))`
3. Index queried columns: `Column(String, index=True)`
4. Use `func.count()` not `len(results)`
5. Paginate all list endpoints — never return unbounded results

---

## Quick Checklist

- [ ] URL uses postgresql+asyncpg://
- [ ] pool_pre_ping=True, pool_recycle=1800
- [ ] expire_on_commit=False
- [ ] Engine disposed in lifespan shutdown
- [ ] Base with TimestampMixin on all entities
- [ ] BaseAsyncRepository for generic CRUD
- [ ] Alembic uses `ddmmyyyy_hhmmss_<slug>` file naming (UTC, 8-digit date)
- [ ] One migration per table / per logical DDL change — autogenerate output split if it bundles multiple
- [ ] Slug follows convention: `create_<table>_table`, `add_<col>_to_<table>`, `add_<name>_index_to_<table>`, `backfill_<table>_<purpose>`
- [ ] Alembic env.py configured for async
- [ ] All models imported in env.py for autogenerate
- [ ] List endpoints paginated

---

## Examples in this skill

- [examples/database.py](examples/database.py) — async engine, session factory, FastAPI session dep
- [examples/base_repository.py](examples/base_repository.py) — `BaseAsyncRepository` with generic CRUD + domain `NotFound` / `AlreadyExists`
- [examples/alembic_env.py](examples/alembic_env.py) — async-ready Alembic `env.py`
- [tests/test_base_repository_example.py](tests/test_base_repository_example.py) — repo tests covering CRUD, unique-violation, pagination edges