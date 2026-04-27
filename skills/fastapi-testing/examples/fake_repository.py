"""FakeRepository demonstrates Protocol-based testing without mocking libraries.

The service depends on the `UserRepository` Protocol. Production passes the
SQLAlchemy impl; tests pass `FakeUserRepository`. No `unittest.mock` needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

UserId = int


@dataclass
class User:
    id: UserId
    email: str
    name: str
    is_active: bool = True


class UserRepository(Protocol):
    async def get(self, user_id: UserId) -> User | None: ...
    async def get_by_email(self, email: str) -> User | None: ...
    async def list(self, *, page: int, size: int) -> tuple[list[User], int]: ...
    async def save(self, user: User) -> User: ...
    async def delete(self, user_id: UserId) -> None: ...


@dataclass
class FakeUserRepository:
    """In-memory implementation. Same shape as the SQLAlchemy version."""

    _store: dict[UserId, User] = field(default_factory=dict)
    _next_id: int = 1

    async def get(self, user_id: UserId) -> User | None:
        return self._store.get(user_id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._store.values() if u.email == email), None)

    async def list(self, *, page: int, size: int) -> tuple[list[User], int]:
        users = sorted(self._store.values(), key=lambda u: u.id)
        start = (page - 1) * size
        return users[start : start + size], len(users)

    async def save(self, user: User) -> User:
        if user.id == 0:
            user.id = self._next_id
            self._next_id += 1
        self._store[user.id] = user
        return user

    async def delete(self, user_id: UserId) -> None:
        self._store.pop(user_id, None)

    # Test helpers ---------------------------------------------------------
    def seed(self, *users: User) -> None:
        for u in users:
            self._store[u.id] = u
            self._next_id = max(self._next_id, u.id + 1)
