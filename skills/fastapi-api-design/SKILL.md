---
name: fastapi-api-design
description: >
  Implement FastAPI API design patterns including FE-friendly standardized
  response format, API versioning with URL paths, Pydantic schema design,
  Annotated dependency injection, pagination, and deprecation strategies.
  Use this skill whenever the user asks about API versioning, standardized
  responses, response format, Pydantic schemas, request/response models,
  API deprecation, sunset headers, endpoint design, pagination, or
  "consistent API format". Works with both simple and modular structures.
  Python 3.12+, Annotated DI, FE-friendly error format.
---

# FastAPI API Design Skill

Consistent API design: FE-friendly responses, versioning, schemas, pagination, deprecation.

---

## FE-Friendly Response Format

**Every** response (success AND error) has the same shape so frontend uses ONE handler:

### Success Response

```json
{
  "success": true,
  "code": 200,
  "message": "User retrieved successfully",
  "data": { "id": 1, "email": "alice@example.com" },
  "errors": null
}
```

### Validation Error (422)

```json
{
  "success": false,
  "code": 422,
  "message": "Validation failed",
  "data": null,
  "errors": [
    { "field": "email", "message": "Invalid email format" },
    { "field": "password", "message": "Must be at least 8 characters" }
  ]
}
```

### Other Errors (401, 403, 404, 409, 500)

```json
{
  "success": false,
  "code": 404,
  "message": "User with id '99' not found",
  "data": null,
  "errors": null
}
```

### Schema Implementation

```python
# schemas/common.py
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

### Frontend TypeScript Contract

```typescript
interface ApiResponse<T> {
  success: boolean;
  code: number;
  message: string;
  data: T | null;
  errors: { field: string; message: string }[] | null;
}
```

---

## Endpoint Patterns

### Create (POST)

```python
@router.post("/", response_model=StandardResponse[UserResponse], status_code=201)
async def create_user(data: UserCreate, service: UserServiceDep):
    user = await service.create_user(data)
    return StandardResponse(code=201, data=user, message="User created successfully")
```

### Read One (GET)

```python
@router.get("/{user_id}", response_model=StandardResponse[UserResponse])
async def get_user(user_id: int, service: UserServiceDep):
    user = await service.get_by_id(user_id)
    return StandardResponse(data=user)
```

### List with Pagination (GET)

```python
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
```

### Update (PATCH)

```python
@router.patch("/{user_id}", response_model=StandardResponse[UserResponse])
async def update_user(user_id: int, data: UserUpdate, service: UserServiceDep):
    user = await service.update_user(user_id, data)
    return StandardResponse(data=user, message="User updated successfully")
```

### Delete (DELETE)

```python
@router.delete("/{user_id}", response_model=StandardResponse[None])
async def delete_user(user_id: int, service: UserServiceDep):
    await service.delete_user(user_id)
    return StandardResponse(message="User deleted successfully")
```

---

## Pydantic Schema Design

### Naming: Base / Create / Update / Response

```python
# schemas/UserSchema.py
from pydantic import BaseModel, EmailStr, Field
from datetime import datetime


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=100)


class UserCreate(UserBase):
    password: str = Field(..., min_length=8, max_length=128)


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    full_name: str | None = Field(None, min_length=1, max_length=100)


class UserResponse(UserBase):
    id: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
```

### Schema Rules

1. Never expose passwords in response schemas
2. `model_config = {"from_attributes": True}` on response schemas
3. Update schemas: all fields `Optional` (PATCH semantics)
4. Use `Field()` for constraints
5. Separate Base/Create/Update/Response — never reuse

---

## Annotated Dependency Injection

Always define type aliases in `dependencies.py`:

```python
from typing import Annotated
from fastapi import Depends

DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[User, Depends(get_current_user)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
ItemServiceDep = Annotated[ItemService, Depends(get_item_service)]
```

Use in endpoints — clean signatures:

```python
@router.get("/me")
async def get_me(user: CurrentUser, service: UserServiceDep):
    ...
```

---

## API Versioning

URL path versioning: `/api/v1/`, `/api/v2/`.

```python
# main.py
app.include_router(api_v1_router, prefix="/api/v1")
app.include_router(api_v2_router, prefix="/api/v2")
```

Create V2 for **breaking changes** only: removed fields, changed types, removed endpoints.
**Non-breaking** changes (new optional fields, new endpoints): add to current version.

### Deprecation Middleware

```python
class APIDeprecationMiddleware(BaseHTTPMiddleware):
    DEPRECATED = {"/api/v1": {"sunset": "2026-01-01", "msg": "Migrate to /api/v2"}}

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        for prefix, info in self.DEPRECATED.items():
            if request.url.path.startswith(prefix):
                response.headers["Deprecation"] = "true"
                response.headers["Sunset"] = info["sunset"]
                response.headers["X-Deprecation-Notice"] = info["msg"]
        return response
```

---

## Quick Checklist

- [ ] Every endpoint returns `StandardResponse` or `PaginatedResponse`
- [ ] `success`, `code`, `message`, `data`, `errors` in every response
- [ ] Validation errors: `errors: [{field, message}]` array
- [ ] Non-validation errors: `errors: null`, message explains the issue
- [ ] Schemas: Base/Create/Update/Response pattern
- [ ] Python 3.12 types: `str | None`, `list[str]`
- [ ] Annotated DI aliases in `dependencies.py`
- [ ] API versioned under `/api/v1/`
- [ ] Deprecated endpoints have Sunset headers