---
name: fastapi-modular
description: >
  Generate a modular FastAPI project structure for large, enterprise-grade APIs
  (50+ endpoints, 4+ developers, multiple business domains). Use this skill
  when the user asks for "modular", "enterprise", "scalable", "large-scale",
  or "domain-driven" FastAPI project, or when requirements involve multiple
  business domains (billing + users + analytics + notifications). Also trigger
  for "microservice-like monolith", "module-based", or 50+ endpoints. Uses
  Poetry, Python 3.12+, Ruff, Annotated DI, Protocol repos, Cache-Aside
  pattern, event bus, and FE-friendly responses. Do NOT use for small/simple
  projects — use fastapi-simple instead.
---

# FastAPI Modular Structure Skill

Domain-based modular architecture for large FastAPI applications.
Poetry + Python 3.12+ | Ruff | Annotated DI | Protocol repos | Event bus

---

## Decision Check

Use when **any** are true: 50+ endpoints, 4+ devs, multiple domains, enterprise maintenance focus.
Otherwise use **fastapi-simple**.

---

## Directory Layout

```
project_root/
├── app/
│   ├── __init__.py
│   ├── main.py                         # FastAPI app + lifespan
│   ├── config/
│   │   ├── __init__.py
│   │   ├── settings.py                 # SettingsConfigDict
│   │   └── database.py                 # Async engine + session
│   ├── core/
│   │   ├── __init__.py
│   │   ├── security.py
│   │   ├── exceptions.py               # Base exceptions + handlers
│   │   ├── middleware.py               # RequestID, security headers
│   │   └── dependencies.py            # Global DI: DbSession, CurrentUser
│   ├── shared/
│   │   ├── __init__.py
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   └── common.py              # StandardResponse, PaginatedResponse, FieldError
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── base.py                # Base, TimestampMixin, SoftDeleteMixin
│   │   ├── repositories/
│   │   │   ├── __init__.py
│   │   │   ├── protocols.py           # Base repository Protocol
│   │   │   └── base.py                # BaseAsyncRepository
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   └── base.py                # BaseService (logging, patterns)
│   │   ├── events/
│   │   │   ├── __init__.py
│   │   │   └── event_bus.py           # Async event bus
│   │   └── utils/
│   │       ├── __init__.py
│   │       ├── logger.py
│   │       └── helpers.py
│   ├── modules/
│   │   ├── __init__.py
│   │   ├── auth/
│   │   │   ├── __init__.py             # exports auth_router
│   │   │   ├── api/
│   │   │   │   └── endpoints.py
│   │   │   ├── services/
│   │   │   │   └── AuthService.py
│   │   │   ├── repositories/
│   │   │   │   ├── protocols.py        # AuthRepositoryProtocol
│   │   │   │   └── AuthRepository.py
│   │   │   ├── models/
│   │   │   │   └── AuthToken.py
│   │   │   ├── schemas/
│   │   │   │   └── AuthSchema.py
│   │   │   └── dependencies.py         # Module-specific DI
│   │   ├── users/
│   │   │   ├── __init__.py
│   │   │   ├── api/
│   │   │   │   └── endpoints.py
│   │   │   ├── services/
│   │   │   │   └── UserService.py
│   │   │   ├── repositories/
│   │   │   │   ├── protocols.py        # UserRepositoryProtocol
│   │   │   │   ├── UserRepository.py
│   │   │   │   └── CachedUserRepository.py
│   │   │   ├── models/
│   │   │   │   ├── User.py
│   │   │   │   └── UserProfile.py
│   │   │   ├── schemas/
│   │   │   │   └── UserSchema.py
│   │   │   └── dependencies.py
│   │   ├── billing/
│   │   └── notifications/
│   │       └── events/
│   │           └── handlers.py         # Subscribes to cross-module events
│   └── api/
│       ├── __init__.py
│       ├── router.py
│       └── v1/
│           └── router.py              # Aggregates all module routers
├── tests/
│   ├── conftest.py
│   └── modules/
│       ├── auth/
│       └── users/
├── migrations/
├── .env.example
├── pyproject.toml
├── Makefile
├── Dockerfile
└── docker-compose.yml
```

---

## Module Anatomy

Every module is self-contained:

```
module_name/
├── __init__.py          # Exports router
├── api/endpoints.py     # FastAPI router
├── services/            # Business logic (depends on Protocol)
├── repositories/
│   ├── protocols.py     # Repository Protocol for this module
│   ├── EntityRepo.py    # Concrete implementation
│   └── CachedEntityRepo.py  # Optional cache layer
├── models/              # SQLAlchemy models
├── schemas/             # Pydantic schemas
├── dependencies.py      # Module Annotated DI aliases
└── events/ (optional)   # Event handlers
```

### Module __init__.py

```python
# app/modules/users/__init__.py
from app.modules.users.api.endpoints import router as users_router

__all__ = ["users_router"]
```

### Module dependencies.py

```python
# app/modules/users/dependencies.py
from typing import Annotated
from fastapi import Depends
from app.core.dependencies import DbSession
from app.modules.users.repositories.UserRepository import UserRepository
from app.modules.users.services.UserService import UserService


def get_user_service(db: DbSession) -> UserService:
    repo = UserRepository(db)
    return UserService(repo)

UserServiceDep = Annotated[UserService, Depends(get_user_service)]
```

### API Router Aggregation

```python
# app/api/v1/router.py
from fastapi import APIRouter
from app.modules.auth import auth_router
from app.modules.users import users_router
from app.modules.billing import billing_router

api_v1_router = APIRouter()
api_v1_router.include_router(auth_router, prefix="/auth", tags=["Auth"])
api_v1_router.include_router(users_router, prefix="/users", tags=["Users"])
api_v1_router.include_router(billing_router, prefix="/billing", tags=["Billing"])
```

---

## Inter-Module Communication

Modules **never** import from each other's internals. Use these patterns:

### 1. Event Bus (preferred for side effects)

```python
# shared/events/event_bus.py
from typing import Any, Callable

class EventBus:
    _handlers: dict[str, list[Callable]] = {}

    @classmethod
    def subscribe(cls, event_name: str, handler: Callable):
        cls._handlers.setdefault(event_name, []).append(handler)

    @classmethod
    async def publish(cls, event_name: str, data: Any):
        for handler in cls._handlers.get(event_name, []):
            await handler(data)

# users module publishes:
await EventBus.publish("user.created", {"user_id": user.id, "email": user.email})

# notifications module subscribes:
EventBus.subscribe("user.created", send_welcome_email)
```

### 2. Shared Protocol Interface

```python
# shared/repositories/protocols.py
from typing import Protocol

class UserLookupProtocol(Protocol):
    async def get_user_email(self, user_id: int) -> str | None: ...

# billing module depends on the protocol, not the users module
```

### 3. API-Level Composition (for read-only cross-module data)

```python
@router.get("/dashboard")
async def dashboard(
    user_svc: UserServiceDep,
    billing_svc: BillingServiceDep,
):
    user = await user_svc.get_current()
    invoices = await billing_svc.get_user_invoices(user.id)
    return StandardResponse(data={"user": user, "invoices": invoices})
```

---

## Migration from Simple to Modular

When to migrate:
- 50+ endpoints
- 4+ devs with merge conflicts
- Multiple distinct domains emerging

Steps:
1. Create `app/modules/` and `app/shared/`
2. Move each domain's files into its own module
3. Move common code into `shared/`
4. Add `protocols.py` per module
5. Update imports and API router aggregation
6. Mirror test structure to modules
7. Run full test suite

---

## Quick Checklist

- [ ] Each module is self-contained with its own protocols, repos, services
- [ ] No direct cross-module imports — use events, protocols, or DI
- [ ] Shared code in `app/shared/`, not duplicated
- [ ] Module `__init__.py` exports its router
- [ ] Module `dependencies.py` has Annotated type aliases
- [ ] All responses use `StandardResponse` / `PaginatedResponse`
- [ ] Validation errors: `errors: [{field, message}]`
- [ ] Python 3.12+ syntax, Ruff, Poetry
- [ ] Tests mirror module structure