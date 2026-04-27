---
name: fastapi-typing
description: >
  Enforce type-annotation discipline in FastAPI projects: PEP 604 unions,
  Annotated dependency injection, Protocol-based contracts, TypedDict for
  structured dicts, generics, NewType for IDs, mypy/pyright strict configs,
  ruff type-checking lints, banning Any, and CI gates. Use this skill
  whenever the user asks about type hints, mypy, pyright, type checking,
  Annotated, Protocol, TypedDict, generics, "is this typed correctly", or
  setting up strict typing for a Python/FastAPI project. Python 3.12+.
---

# FastAPI Typing Skill

Strict, useful types: catch bugs at edit-time, document intent, enable refactoring. Python 3.12+.

---

## Standards

1. **Every public function** has parameter types AND a return type.
2. **No `Any`** without an inline justification comment.
3. **Use modern syntax:** `X | None` not `Optional[X]`, `list[X]` not `List[X]`.
4. **`Annotated[T, Depends(...)]`** for all DI — never positional `Depends()`.
5. **`Protocol`** for structural contracts (repos, services), not ABCs.
6. **`NewType`** for IDs that should not mix (`UserId`, `OrderId`).
7. **`TypedDict` / `dataclass` / Pydantic** for structured dicts — never bare `dict`.
8. **Strict mode in CI**: mypy `--strict` or pyright `strict`.

---

## Modern Type Syntax (Python 3.12+)

```python
# Yes
def f(x: int | None, items: list[str], by_id: dict[int, User]) -> User | None: ...

# No
from typing import Optional, List, Dict, Tuple
def f(x: Optional[int], items: List[str], by_id: Dict[int, User]) -> Optional[User]: ...
```

Use `from __future__ import annotations` only if supporting < 3.10. On 3.12+ it's unnecessary.

---

## Annotated Dependency Injection

```python
from typing import Annotated
from fastapi import Depends

DBSession = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
UserRepoDep = Annotated[UserRepo, Depends()]

@router.get("/me")
async def me(user: CurrentUser, repo: UserRepoDep, session: DBSession) -> UserOut: ...
```

Aliases at module top, endpoints stay clean. `Depends()` (no arg) auto-resolves the class via constructor type hints.

---

## NewType for IDs

```python
from typing import NewType

UserId = NewType("UserId", int)
OrderId = NewType("OrderId", int)

def get_user(uid: UserId) -> User: ...

uid: UserId = UserId(42)
oid: OrderId = OrderId(7)

get_user(oid)  # type error — OrderId is not UserId
```

Catches the entire class of "passed the wrong ID" bugs at compile time. Cost: zero runtime overhead.

---

## Protocol vs ABC

`Protocol` = structural typing (duck-typed). `ABC` = nominal (must inherit). For repos and services, `Protocol` is friendlier:

```python
from typing import Protocol

class UserRepository(Protocol):
    async def get(self, user_id: UserId) -> User | None: ...
    async def list(self, *, page: int, size: int) -> tuple[list[User], int]: ...
    async def save(self, user: User) -> User: ...

# Production impl — no inheritance needed
class SqlUserRepository:
    def __init__(self, session: AsyncSession): self.session = session
    async def get(self, user_id: UserId) -> User | None: ...
    ...

# Test impl — also no inheritance
class FakeUserRepository:
    def __init__(self): self._store: dict[UserId, User] = {}
    async def get(self, user_id: UserId) -> User | None: ...
```

Service depends on the `Protocol`, not the impl. Tests pass `FakeUserRepository` directly — no mocking library.

For runtime checks: `@runtime_checkable` decorator (rarely needed).

---

## TypedDict for Structured Dicts

When you can't (or shouldn't) reach for Pydantic — internal payloads, JWT claims, cache values:

```python
from typing import TypedDict, NotRequired

class JwtClaims(TypedDict):
    sub: str
    exp: int
    iat: int
    scopes: list[str]
    tenant_id: NotRequired[str]
```

Better than `dict[str, Any]` everywhere.

---

## Generics

```python
from typing import Generic, TypeVar

T = TypeVar("T")

class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int

UserPage = Page[UserOut]
```

For repository base:
```python
from typing import Generic, TypeVar
from sqlalchemy.orm import DeclarativeBase

ModelT = TypeVar("ModelT", bound=DeclarativeBase)

class BaseRepo(Generic[ModelT]):
    model: type[ModelT]
    async def get(self, id: int) -> ModelT | None: ...
```

---

## Banning `Any`

mypy / pyright let it through silently if disallowed flags aren't set. Turn them on (see configs below). When `Any` is unavoidable (e.g., 3rd-party untyped lib), document it:

```python
result: Any = legacy_lib.do_thing()  # any: legacy_lib has no stubs (issue #142)
```

Grep for `: Any` and `# type: ignore` periodically — both should be rare and explained.

---

## mypy Config (Strict)

```toml
# pyproject.toml
[tool.mypy]
python_version = "3.12"
strict = true
warn_unused_ignores = true
warn_unreachable = true
disallow_any_explicit = false  # allow explicit Any with comment, ban implicit
disallow_any_unimported = true
no_implicit_reexport = true
plugins = ["pydantic.mypy"]

[[tool.mypy.overrides]]
module = ["tests.*"]
disallow_untyped_decorators = false   # pytest fixtures are tricky

[[tool.mypy.overrides]]
module = ["legacy_lib.*"]
ignore_missing_imports = true
```

`strict = true` enables: `disallow_untyped_defs`, `disallow_incomplete_defs`, `check_untyped_defs`, `disallow_untyped_decorators`, `no_implicit_optional`, `warn_redundant_casts`, `warn_unused_ignores`, `warn_return_any`, `no_implicit_reexport`, `strict_equality`, `extra_checks`.

---

## Pyright Config (Strict)

Faster than mypy, better Pydantic v2 support:

```json
// pyrightconfig.json
{
  "include": ["app", "tests"],
  "exclude": ["**/__pycache__", "**/.venv"],
  "pythonVersion": "3.12",
  "typeCheckingMode": "strict",
  "reportMissingTypeStubs": "warning",
  "reportImplicitOverride": "error",
  "reportPrivateUsage": "warning",
  "reportUnnecessaryTypeIgnoreComment": "error",
  "reportUnusedImport": "error"
}
```

Pick **one** (mypy or pyright). Running both wastes CI time and produces conflicting hints.

---

## Ruff Type Lints

```toml
# pyproject.toml
[tool.ruff.lint]
select = [
  "E", "F", "W", "I",         # baseline
  "B",                        # bugbear
  "UP",                       # pyupgrade — modernize type syntax
  "ANN",                      # flake8-annotations — require annotations
  "TCH",                      # flake8-type-checking — TYPE_CHECKING optimization
  "PYI",                      # pyi best practices
  "TID",                      # tidy imports
]
ignore = ["ANN101", "ANN102"]  # don't require self/cls annotations

[tool.ruff.lint.per-file-ignores]
"tests/**/*.py" = ["ANN"]      # tests can be looser
```

`UP` auto-rewrites `Optional[X]` → `X | None`, `List` → `list`. Run `ruff check --fix`.

---

## Pydantic v2 + mypy

```toml
[tool.mypy]
plugins = ["pydantic.mypy"]

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true
```

Catches: missing required fields in `Model(...)`, wrong field types, alias misuse.

---

## SQLAlchemy 2.x Typed Models

Use `Mapped[T]` everywhere — both columns and relationships:

```python
from datetime import datetime
from sqlalchemy import String, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    created_at: Mapped[datetime]
    posts: Mapped[list["Post"]] = relationship(back_populates="author")
```

mypy/pyright now understand `User.email` is `str`.

---

## CI Gate

```yaml
# .github/workflows/ci.yml (snippet)
- run: ruff check .
- run: ruff format --check .
- run: pyright          # or: mypy app
- run: pytest -q --cov=app --cov-fail-under=80
```

Fail the build on any type error. Don't ship un-typed code.

---

## Anti-patterns

| Don't | Why |
|------|-----|
| `from typing import Optional, List, Dict` on 3.12 | Use built-ins / `\|` syntax |
| `def f(x):` (no annotations) | Becomes invisible to type checker |
| `# type: ignore` with no comment | Hides real bugs; require justification |
| `Any` in service signatures | Defeats typing for whole call chain |
| `dict[str, Any]` for known-shape payload | Use `TypedDict` or Pydantic |
| `cast(T, x)` to silence the checker | Usually means the type is actually wrong |
| Inheriting from `ABC` for a 3-method repo | `Protocol` is lighter and more flexible |

---

## Verification Checklist

- [ ] `pyright` (or `mypy --strict`) passes on `app/` with zero errors
- [ ] No `Any` in `app/` without `# any:` justification
- [ ] All `Depends` use `Annotated[T, Depends(...)]`
- [ ] Repo contracts are `Protocol`s
- [ ] IDs are `NewType`s in modules where confusion is possible
- [ ] Ruff `ANN` + `UP` rules enabled and clean
- [ ] CI fails the build on type errors
