"""Reference repository tests against a real Postgres test DB.

Demonstrates: happy-path CRUD, NotFound, unique-constraint, pagination edges.
"""
from __future__ import annotations

import pytest
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ..examples.base_repository import (
    AlreadyExists,
    BaseAsyncRepository,
    NotFound,
)
from ..examples.database import Base

pytestmark = pytest.mark.asyncio


class Widget(Base):
    __tablename__ = "test_widgets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)


class WidgetRepo(BaseAsyncRepository[Widget]):
    model = Widget


# ---- Create / Get -------------------------------------------------------

async def test_add_then_get(session):
    repo = WidgetRepo(session)
    w = await repo.add(Widget(name="alpha"))
    assert w.id > 0
    fetched = await repo.get(w.id)
    assert fetched is not None
    assert fetched.name == "alpha"


async def test_get_missing_returns_none(session):
    repo = WidgetRepo(session)
    assert await repo.get(999_999) is None


async def test_get_or_404_raises(session):
    repo = WidgetRepo(session)
    with pytest.raises(NotFound):
        await repo.get_or_404(999_999)


# ---- Unique constraint -----------------------------------------------------

async def test_duplicate_name_raises_already_exists(session):
    repo = WidgetRepo(session)
    await repo.add(Widget(name="dup"))
    with pytest.raises(AlreadyExists):
        await repo.add(Widget(name="dup"))


# ---- Pagination ------------------------------------------------------------

async def test_list_pagination_boundaries(session):
    repo = WidgetRepo(session)
    for i in range(15):
        await repo.add(Widget(name=f"w{i}"))

    page1, total = await repo.list(page=1, size=10)
    assert total == 15
    assert len(page1) == 10

    page2, _ = await repo.list(page=2, size=10)
    assert len(page2) == 5

    empty, _ = await repo.list(page=99, size=10)
    assert empty == []


# ---- Update / Delete -------------------------------------------------------

async def test_update_and_delete(session):
    repo = WidgetRepo(session)
    w = await repo.add(Widget(name="original"))
    await repo.update(w, name="renamed")
    refetched = await repo.get(w.id)
    assert refetched.name == "renamed"

    await repo.delete(refetched)
    assert await repo.get(w.id) is None
