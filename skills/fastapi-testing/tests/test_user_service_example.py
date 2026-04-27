"""Service-layer unit tests using FakeUserRepository (no DB, no mocks)."""
from __future__ import annotations

import pytest

from ..examples.fake_repository import FakeUserRepository, User

pytestmark = pytest.mark.asyncio


class UserService:
    """Trimmed example. In real code, import from app.services.user."""

    def __init__(self, repo: FakeUserRepository):
        self.repo = repo

    async def register(self, *, email: str, name: str) -> User:
        if await self.repo.get_by_email(email):
            raise ValueError("email already registered")
        return await self.repo.save(User(id=0, email=email.lower().strip(), name=name.strip()))


async def test_register_happy_path():
    repo = FakeUserRepository()
    svc = UserService(repo)

    user = await svc.register(email="A@B.com ", name=" Ada ")

    assert user.id > 0
    assert user.email == "a@b.com"
    assert user.name == "Ada"


async def test_register_duplicate_email_raises():
    repo = FakeUserRepository()
    repo.seed(User(id=1, email="dup@x.com", name="First"))
    svc = UserService(repo)

    with pytest.raises(ValueError, match="already registered"):
        await svc.register(email="dup@x.com", name="Second")


async def test_register_normalizes_email_case_for_dedup_check():
    repo = FakeUserRepository()
    repo.seed(User(id=1, email="dup@x.com", name="First"))
    svc = UserService(repo)

    # Service should treat "DUP@x.com" as same email — adjust impl to match
    with pytest.raises(ValueError):
        await svc.register(email="DUP@x.com", name="Other")
