---
name: fastapi-logging
description: >
  Implement structured JSON logging for FastAPI with request ID tracking,
  user context, environment-specific configuration, and request/response
  logging middleware. Use this skill whenever the user asks about logging,
  structured logs, JSON logging, request tracing, request ID, log correlation,
  log middleware, or monitoring. Also trigger for "observability", "log format",
  "request tracking", "correlation ID", or "log context". Python 3.12+.
---

# FastAPI Structured Logging Skill

JSON logging with request tracing and contextual information. Python 3.12+.

---

## Logger Setup

```python
# utils/logger.py
import logging
import sys
from pythonjsonlogger import jsonlogger
from app.config.settings import settings


def setup_logger(name: str = "app") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper()))

    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)

    if settings.DEBUG:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
        )
    else:
        formatter = jsonlogger.JsonFormatter(
            fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )

    handler.setFormatter(formatter)
    logger.addHandler(handler)
    return logger


logger = setup_logger()
```

Dependency: `poetry add python-json-logger`

---

## Request ID Middleware

```python
# core/middleware.py
import uuid
from contextvars import ContextVar
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request

request_id_var: ContextVar[str] = ContextVar("request_id", default="")


class RequestIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        req_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request_id_var.set(req_id)
        request.state.request_id = req_id

        response = await call_next(request)
        response.headers["X-Request-ID"] = req_id
        return response


def get_request_id() -> str:
    return request_id_var.get()
```

---

## Request/Response Logging Middleware

```python
# core/middleware.py (continued)
import time
from app.utils.logger import setup_logger

access_logger = setup_logger("access")


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()

        access_logger.info(
            "Request started",
            extra={
                "request_id": getattr(request.state, "request_id", ""),
                "method": request.method,
                "path": request.url.path,
                "client_ip": request.client.host if request.client else "",
            },
        )

        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        access_logger.info(
            "Request completed",
            extra={
                "request_id": getattr(request.state, "request_id", ""),
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        return response
```

### Register Order in main.py

```python
app.add_middleware(RequestLoggingMiddleware)  # logs timing
app.add_middleware(RequestIDMiddleware)        # sets ID first (runs before logging)
```

---

## Service-Level Logging

```python
# services/UserService.py
from app.utils.logger import setup_logger
from app.core.middleware import get_request_id

logger = setup_logger("services.user")


class UserService:
    def __init__(self, repository: UserRepositoryProtocol):
        self.repository = repository

    async def create_user(self, data):
        logger.info("Creating user", extra={
            "request_id": get_request_id(), "email": data.email,
        })

        if await self.repository.get_by_email(data.email):
            logger.warning("Duplicate email", extra={
                "request_id": get_request_id(), "email": data.email,
            })
            raise ConflictError("User", data.email)

        user = await self.repository.create(data.model_dump())
        logger.info("User created", extra={
            "request_id": get_request_id(), "user_id": user.id,
        })
        return user
```

---

## Environment Config

| Environment | LOG_LEVEL | Format |
|-------------|-----------|--------|
| Development | DEBUG | Human-readable |
| Staging | INFO | JSON |
| Production | WARNING | JSON |

---

## JSON Output Example (Production)

```json
{
  "timestamp": "2025-01-15T09:30:45.123Z",
  "level": "INFO",
  "name": "access",
  "message": "Request completed",
  "request_id": "a1b2c3d4-e5f6-7890",
  "method": "POST",
  "path": "/api/v1/users",
  "status_code": 201,
  "duration_ms": 45.23
}
```

Parseable by ELK, Datadog, CloudWatch, Grafana Loki.

---

## Quick Checklist

- [ ] JSON logger with `python-json-logger`
- [ ] Human-readable in DEBUG, JSON in production
- [ ] RequestIDMiddleware generates/propagates unique IDs
- [ ] X-Request-ID in response headers
- [ ] Request timing logged (duration_ms)
- [ ] Services include request_id in all logs
- [ ] LOG_LEVEL configured per environment