---
name: fastapi-testing
description: >
  Implement testing patterns for FastAPI including async test configuration,
  pytest fixtures for database sessions and authenticated clients, unit tests
  with FakeRepository (no mocking needed thanks to Protocol), integration
  tests validating FE-friendly response format, test coverage config, and
  test organization. Use this skill for testing FastAPI, pytest setup, async
  tests, fixtures, FakeRepository, integration tests, API tests, or test
  coverage. Also trigger for "conftest.py", "test client", "httpx",
  "pytest-asyncio", or "test organization". Python 3.12+.
---

# FastAPI Testing Skill

Async tests with FakeRepository, httpx client, FE-friendly response validation. Python 3.12+.

---

## Test Structure

### Simple Project
```
tests/
├── conftest.py
├── unit/
│   └── test_user_service.py
├── integration/
│   └── test_user_endpoints.py
└── utils/
    ├── fakes.py              # FakeRepository classes
    └── assertions.py         # Response format helpers
```

### Modular Project
```
tests/
├── conftest.py
├── modules/
│   ├── auth/
│   │   └── test_auth_endpoints.py
│   └── users/
│       ├── test_user_service.py
│       └── test_user_endpoints.py
└── utils/
    ├── fakes.py
    └── assertions.py
```

---

## Core conftest.py

```python
# tests/conftest.py
import pytest
from typing import AsyncGenerator
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.main import app
from app.config.database import get_db
from app.models.base import Base
from app.core.security import create_access_token, hash_password

TEST_DATABASE_URL = "sqlite+aiosqlite:///./test.db"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=True)
TestSession = async_sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture(scope="session")
def event_loop():
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(autouse=True)
async def setup_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    async with TestSession() as session:
        yield session


@pytest.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
def user_data() -> dict:
    return {"email": "test@example.com", "full_name": "Test User", "password": "Test1234"}


@pytest.fixture
async def created_user(db_session: AsyncSession, user_data: dict):
    from app.models.User import User
    user = User(
        email=user_data["email"],
        full_name=user_data["full_name"],
        hashed_password=hash_password(user_data["password"]),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def auth_client(client: AsyncClient, created_user) -> AsyncClient:
    token = create_access_token(created_user.id)
    client.headers["Authorization"] = f"Bearer {token}"
    return client
```

Dependencies: `poetry add --group dev pytest pytest-asyncio httpx aiosqlite`

---

## FakeRepository (No Mocking Needed)

Because services depend on Protocol, you can use simple fakes instead of `AsyncMock`:

```python
# tests/utils/fakes.py
from app.models.User import User


class FakeUserRepository:
    """In-memory repo satisfying UserRepositoryProtocol."""

    def __init__(self):
        self.users: dict[int, User] = {}
        self._next_id = 1

    async def get_by_id(self, id: int) -> User | None:
        return self.users.get(id)

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.users.values() if u.email == email), None)

    async def create(self, obj_data: dict) -> User:
        user = User(id=self._next_id, **obj_data)
        self.users[user.id] = user
        self._next_id += 1
        return user

    async def update(self, db_obj: User, update_data: dict) -> User:
        for key, val in update_data.items():
            if val is not None:
                setattr(db_obj, key, val)
        return db_obj

    async def delete(self, db_obj: User) -> None:
        self.users.pop(db_obj.id, None)

    async def count(self, **filters) -> int:
        return len(self.users)

    async def get_active_users(self) -> list[User]:
        return [u for u in self.users.values() if u.is_active]
```

---

## Unit Tests (Service Layer)

Clean, fast, no mocking libraries:

```python
# tests/unit/test_user_service.py
import pytest
from app.services.UserService import UserService
from app.core.exceptions import NotFoundError, ConflictError
from tests.utils.fakes import FakeUserRepository


class TestUserService:
    @pytest.fixture
    def repo(self):
        return FakeUserRepository()

    @pytest.fixture
    def service(self, repo):
        return UserService(repo)

    @pytest.mark.asyncio
    async def test_get_by_id_found(self, service, repo):
        await repo.create({"email": "a@b.com", "full_name": "Alice", "hashed_password": "x"})
        user = await service.get_by_id(1)
        assert user.email == "a@b.com"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, service):
        with pytest.raises(NotFoundError):
            await service.get_by_id(999)

    @pytest.mark.asyncio
    async def test_create_user_success(self, service):
        from unittest.mock import MagicMock
        data = MagicMock()
        data.email = "new@b.com"
        data.model_dump.return_value = {"email": "new@b.com", "full_name": "New", "hashed_password": "x"}
        user = await service.create_user(data)
        assert user.email == "new@b.com"

    @pytest.mark.asyncio
    async def test_create_duplicate_email(self, service, repo):
        await repo.create({"email": "dup@b.com", "full_name": "Dup", "hashed_password": "x"})
        from unittest.mock import MagicMock
        data = MagicMock()
        data.email = "dup@b.com"
        with pytest.raises(ConflictError):
            await service.create_user(data)
```

---

## Integration Tests (Endpoints)

Validate the full FE-friendly response format:

```python
# tests/integration/test_user_endpoints.py
import pytest
from httpx import AsyncClient


class TestUserEndpoints:
    @pytest.mark.asyncio
    async def test_create_user(self, client: AsyncClient, user_data):
        response = await client.post("/api/v1/users/", json=user_data)
        assert response.status_code == 201
        body = response.json()

        # Verify FE-friendly format
        assert body["success"] is True
        assert body["code"] == 201
        assert body["data"]["email"] == user_data["email"]
        assert body["errors"] is None
        assert "password" not in body["data"]

    @pytest.mark.asyncio
    async def test_create_user_duplicate(self, client: AsyncClient, created_user, user_data):
        response = await client.post("/api/v1/users/", json=user_data)
        assert response.status_code == 409
        body = response.json()
        assert body["success"] is False
        assert body["errors"] is None  # not a validation error

    @pytest.mark.asyncio
    async def test_validation_error_format(self, client: AsyncClient):
        response = await client.post("/api/v1/users/", json={"email": "bad"})
        assert response.status_code == 422
        body = response.json()

        assert body["success"] is False
        assert body["code"] == 422
        assert body["message"] == "Validation failed"
        assert body["data"] is None
        assert isinstance(body["errors"], list)
        # Each error has field + message
        for err in body["errors"]:
            assert "field" in err
            assert "message" in err
            assert "body." not in err["field"]  # no ugly prefix

    @pytest.mark.asyncio
    async def test_get_me_authenticated(self, auth_client: AsyncClient):
        response = await auth_client.get("/api/v1/users/me")
        assert response.status_code == 200
        assert response.json()["success"] is True

    @pytest.mark.asyncio
    async def test_get_me_unauthenticated(self, client: AsyncClient):
        response = await client.get("/api/v1/users/me")
        assert response.status_code == 401
        assert response.json()["success"] is False
```

---

## Response Format Assertion Helper

```python
# tests/utils/assertions.py

def assert_success(response, expected_code: int = 200):
    body = response.json()
    assert response.status_code == expected_code
    assert body["success"] is True
    assert body["code"] == expected_code
    assert body["errors"] is None


def assert_error(response, expected_code: int):
    body = response.json()
    assert response.status_code == expected_code
    assert body["success"] is False
    assert body["code"] == expected_code


def assert_validation_error(response):
    body = response.json()
    assert response.status_code == 422
    assert body["success"] is False
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) > 0
    for err in body["errors"]:
        assert "field" in err and "message" in err
```

---

## pytest Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
addopts = "-v --tb=short -x"
markers = [
    "slow: slow tests",
    "integration: integration tests",
    "unit: unit tests",
]

[tool.coverage.run]
source = ["app"]
omit = ["app/config/*", "tests/*", "migrations/*"]

[tool.coverage.report]
fail_under = 80
show_missing = true
```

### Running Tests

```bash
pytest                          # all tests
pytest tests/unit/              # unit only
pytest tests/integration/       # integration only
pytest --cov=app --cov-report=html  # with coverage
```

---

## Quick Checklist

- [ ] Async conftest with test DB (SQLite + aiosqlite)
- [ ] `setup_db` creates/drops tables per test
- [ ] `client` overrides `get_db` dependency
- [ ] `auth_client` provides Bearer token
- [ ] FakeRepository for unit tests (no mocking)
- [ ] Integration tests verify `{success, code, message, data, errors}`
- [ ] Validation tests verify clean field names (no "body." prefix)
- [ ] `asyncio_mode = "auto"` in pytest config
- [ ] Coverage: `fail_under = 80`

---

## Per-Layer Test-Case Catalog

For a complete checklist of **which tests must exist at each layer** (schema, repository, service, endpoint, auth, background tasks, migrations, file uploads, contract, performance), see [references/test-case-catalog.md](references/test-case-catalog.md).

Use it as a definition-of-done before declaring a feature complete.

---

## Examples in this skill

- [examples/conftest.py](examples/conftest.py) — reusable async fixtures (engine, rolling-back session, app override, auth_client)
- [examples/fake_repository.py](examples/fake_repository.py) — `Protocol`-based fake repo for unit tests, no mocking lib
- [tests/test_user_endpoints_example.py](tests/test_user_endpoints_example.py) — reference integration test set demonstrating envelope assertions and status-code coverage
- [tests/test_user_service_example.py](tests/test_user_service_example.py) — reference service-layer unit tests using the fake repo