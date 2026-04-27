"""Generic async base repository with CRUD primitives.

Usage:
    class UserRepository(BaseAsyncRepository[User]):
        model = User
"""
from __future__ import annotations

from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, NoResultFound
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase

ModelT = TypeVar("ModelT", bound=DeclarativeBase)


class AlreadyExists(Exception):
    """Domain exception for unique-constraint violations."""


class NotFound(Exception):
    """Domain exception for missing rows."""


class BaseAsyncRepository(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get(self, id_: int) -> ModelT | None:
        return await self.session.get(self.model, id_)

    async def get_or_404(self, id_: int) -> ModelT:
        obj = await self.get(id_)
        if obj is None:
            raise NotFound(f"{self.model.__name__} {id_} not found")
        return obj

    async def list(
        self, *, page: int = 1, size: int = 20
    ) -> tuple[list[ModelT], int]:
        stmt = select(self.model).order_by(self.model.id)  # type: ignore[attr-defined]
        total = await self.session.scalar(
            select(func.count()).select_from(self.model)
        )
        rows = (await self.session.scalars(stmt.offset((page - 1) * size).limit(size))).all()
        return list(rows), int(total or 0)

    async def add(self, obj: ModelT) -> ModelT:
        self.session.add(obj)
        try:
            await self.session.flush()
        except IntegrityError as e:
            await self.session.rollback()
            raise AlreadyExists(str(e.orig)) from e
        return obj

    async def update(self, obj: ModelT, **fields) -> ModelT:
        for k, v in fields.items():
            setattr(obj, k, v)
        try:
            await self.session.flush()
        except IntegrityError as e:
            await self.session.rollback()
            raise AlreadyExists(str(e.orig)) from e
        return obj

    async def delete(self, obj: ModelT) -> None:
        await self.session.delete(obj)
        await self.session.flush()
