---
name: fastapi-exceptions
description: >
  Implement FE-friendly exception handling for FastAPI including custom
  exception classes, global exception handlers producing consistent
  {success, code, message, data, errors} responses, validation error
  formatting with clean field names (no "body." prefix), and error logging
  with request context. Use this skill whenever the user asks about error
  handling, custom exceptions, exception handlers, validation errors, error
  responses, or "how to handle errors in FastAPI". Also trigger for
  "HTTPException", "422 errors", "global error handler", "FE-friendly errors",
  or "frontend error handling". Python 3.12+.
---

# FastAPI Exception Handling Skill

FE-friendly exceptions: consistent `{success, code, message, data, errors}` for every error.

---

## The Goal

Frontend receives the **same response shape** for every error:

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

Non-validation errors use `errors: null`:

```json
{
  "success": false,
  "code": 404,
  "message": "User with id '99' not found",
  "data": null,
  "errors": null
}
```

---

## Base Exception Class

```python
# core/exceptions.py
from typing import Any
from fastapi import HTTPException


class BaseAPIException(HTTPException):
    def __init__(
        self,
        status_code: int,
        message: str,
        data: Any = None,
        headers: dict[str, str] | None = None,
    ):
        self.message = message
        self.data = data
        super().__init__(status_code=status_code, detail=message, headers=headers)
```

---

## Concrete Exception Classes

```python
class NotFoundError(BaseAPIException):
    def __init__(self, resource: str, identifier: Any):
        super().__init__(
            status_code=404,
            message=f"{resource} with id '{identifier}' not found",
        )


class UnauthorizedError(BaseAPIException):
    def __init__(self, message: str = "Authentication required"):
        super().__init__(status_code=401, message=message)


class ForbiddenError(BaseAPIException):
    def __init__(self, message: str = "Insufficient permissions"):
        super().__init__(status_code=403, message=message)


class ConflictError(BaseAPIException):
    def __init__(self, resource: str, identifier: Any):
        super().__init__(
            status_code=409,
            message=f"{resource} '{identifier}' already exists",
        )


class BadRequestError(BaseAPIException):
    def __init__(self, message: str = "Bad request"):
        super().__init__(status_code=400, message=message)


class RateLimitError(BaseAPIException):
    def __init__(self):
        super().__init__(
            status_code=429,
            message="Rate limit exceeded. Try again later.",
            headers={"Retry-After": "60"},
        )
```

---

## Global Exception Handlers

These catch EVERY error type and produce the consistent FE-friendly response.

```python
# core/exceptions.py (continued)
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

logger = logging.getLogger("app.exceptions")


def register_exception_handlers(app: FastAPI):

    @app.exception_handler(BaseAPIException)
    async def api_exception_handler(request: Request, exc: BaseAPIException):
        request_id = getattr(request.state, "request_id", "unknown")

        logger.warning(
            "API error: %s [%d]",
            exc.message,
            exc.status_code,
            extra={"request_id": request_id, "path": request.url.path},
        )

        return JSONResponse(
            status_code=exc.status_code,
            content={
                "success": False,
                "code": exc.status_code,
                "message": exc.message,
                "data": exc.data,
                "errors": None,
            },
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Convert Pydantic errors to FE-friendly {field, message} array."""
        request_id = getattr(request.state, "request_id", "unknown")

        errors = []
        for error in exc.errors():
            # Extract clean field name: ("body", "email") → "email"
            loc_parts = error["loc"]
            # Skip "body", "query", "path" prefixes
            field_parts = [str(p) for p in loc_parts if p not in ("body", "query", "path", "header")]
            field = ".".join(field_parts) if field_parts else str(loc_parts[-1])

            errors.append({
                "field": field,
                "message": error["msg"],
            })

        logger.warning(
            "Validation error on %s",
            request.url.path,
            extra={"request_id": request_id, "errors": errors},
        )

        return JSONResponse(
            status_code=422,
            content={
                "success": False,
                "code": 422,
                "message": "Validation failed",
                "data": None,
                "errors": errors,
            },
            headers={"X-Request-ID": request_id},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        """Catch-all. Never leak stack traces to frontend."""
        request_id = getattr(request.state, "request_id", "unknown")

        logger.error(
            "Unhandled exception: %s",
            str(exc),
            exc_info=True,
            extra={"request_id": request_id, "path": request.url.path},
        )

        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "code": 500,
                "message": "An unexpected error occurred",
                "data": None,
                "errors": None,
            },
            headers={"X-Request-ID": request_id},
        )
```

---

## Usage in Services

Services raise domain exceptions. The global handler formats them.

```python
class UserService:
    def __init__(self, repository: UserRepositoryProtocol):
        self.repository = repository

    async def get_by_id(self, user_id: int) -> User:
        user = await self.repository.get_by_id(user_id)
        if not user:
            raise NotFoundError("User", user_id)
        return user

    async def create_user(self, data: UserCreate) -> User:
        if await self.repository.get_by_email(data.email):
            raise ConflictError("User", data.email)
        return await self.repository.create(data.model_dump())
```

---

## Complete Error Response Map

| Exception | HTTP | Response |
|-----------|------|----------|
| Pydantic validation | 422 | `errors: [{field, message}]` |
| `NotFoundError` | 404 | `message: "User with id '99' not found"` |
| `UnauthorizedError` | 401 | `message: "Token expired"` |
| `ForbiddenError` | 403 | `message: "Insufficient permissions"` |
| `ConflictError` | 409 | `message: "User 'a@b.com' already exists"` |
| `BadRequestError` | 400 | `message: "Bad request"` |
| `RateLimitError` | 429 | `message: "Rate limit exceeded"` |
| Unhandled | 500 | `message: "An unexpected error occurred"` |

**Every single one** returns `{success, code, message, data, errors}`.

---

## Validation Error Field Name Cleaning

Pydantic gives: `("body", "email")` → our handler returns: `"email"`
Pydantic gives: `("body", "address", "city")` → our handler returns: `"address.city"`
Pydantic gives: `("query", "page")` → our handler returns: `"page"`

The `"body"`, `"query"`, `"path"`, `"header"` prefixes are stripped so field names match the frontend form field names directly.

---

## Quick Checklist

- [ ] All custom exceptions extend `BaseAPIException`
- [ ] `register_exception_handlers(app)` in `main.py`
- [ ] Pydantic errors → `errors: [{field, message}]` with clean field names
- [ ] Non-validation errors → `errors: null`
- [ ] Every error response: `{success: false, code, message, data, errors}`
- [ ] Unhandled exceptions caught — never leak stack traces
- [ ] All errors logged with request_id
- [ ] Services raise domain exceptions, not raw HTTPException