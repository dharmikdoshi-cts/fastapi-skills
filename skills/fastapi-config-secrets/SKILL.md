---
name: fastapi-config-secrets
description: >
  Implement 12-factor configuration and secrets management for FastAPI using
  pydantic-settings v2, layered .env files (.env, .env.local, .env.<env>),
  typed settings with validation, secret providers (AWS Secrets Manager,
  HashiCorp Vault, Doppler), runtime secret rotation, and safe logging that
  redacts sensitive values. Use this skill whenever the user asks about
  configuration, environment variables, .env files, secrets, secret rotation,
  pydantic-settings, BaseSettings, config validation, or "how to manage
  credentials". Also trigger for "12-factor config", "AWS Secrets Manager",
  "Vault", "Doppler", "redact secrets", or "config per environment".
  Python 3.12+, pydantic-settings v2.
---

# FastAPI Config & Secrets Skill

Typed, layered, validated configuration with safe secret handling. Python 3.12+ + pydantic-settings v2.

---

## The Goal

- Single `Settings` object, fully typed, validated at startup (fail-fast).
- Secrets never in source control, never in logs, never in error responses.
- Per-environment overrides without code changes.
- Easy local dev, safe prod.

---

## Settings Definition

```python
# app/config/settings.py
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.local"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="forbid",         # unknown env vars fail loudly
    )

    # --- App ---
    APP_NAME: str = "erp-api"
    ENV: Literal["local", "dev", "staging", "prod"] = "local"
    DEBUG: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- Database ---
    DATABASE_URL: PostgresDsn
    DATABASE_POOL_SIZE: int = Field(default=10, ge=1, le=100)
    DATABASE_MAX_OVERFLOW: int = Field(default=20, ge=0, le=100)

    # --- Redis ---
    REDIS_URL: RedisDsn

    # --- Auth (SECRETS) ---
    JWT_SECRET: SecretStr
    JWT_ALGORITHM: Literal["HS256", "RS256"] = "HS256"
    ACCESS_TOKEN_TTL_MINUTES: int = Field(default=15, ge=1)
    REFRESH_TOKEN_TTL_DAYS: int = Field(default=7, ge=1)

    # --- 3rd party ---
    STRIPE_API_KEY: SecretStr | None = None
    SENTRY_DSN: SecretStr | None = None

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_strong(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET must be at least 32 chars")
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
```

**Always wrap secrets in `SecretStr`.** `repr()` and `str()` print `**********`, so they don't leak into logs, tracebacks, or error responses.

```python
settings.JWT_SECRET             # SecretStr('**********')
settings.JWT_SECRET.get_secret_value()  # 'real-secret-here' — only when needed
```

---

## Layered .env Files

Load order (later overrides earlier):

| File | Committed? | Purpose |
|------|-----------|---------|
| `.env.example` | yes | Template with **dummy** values, documents every var |
| `.env` | **no** | Local dev secrets |
| `.env.local` | **no** | Per-developer overrides |
| `.env.<env>` | depends | CI/staging defaults (no secrets) |

`.gitignore`:
```
.env
.env.local
.env.*.local
```

Never commit a `.env` with real values. CI/prod inject env vars directly via the platform.

---

## Per-Environment Strategy

```bash
# Local dev
ENV=local python -m uvicorn app.main:app --reload

# Staging (env vars injected by platform)
ENV=staging gunicorn app.main:app -k uvicorn.workers.UvicornWorker

# Prod
ENV=prod gunicorn app.main:app ...
```

In code, branch on `settings.ENV`, not on `DEBUG`:

```python
if settings.ENV == "prod":
    app.add_middleware(HTTPSRedirectMiddleware)
```

---

## Secret Providers

For prod, **don't** rely on `.env` files. Pull from a vault at startup.

### AWS Secrets Manager

```python
# app/config/secrets.py
import json
import boto3
from functools import lru_cache


@lru_cache(maxsize=1)
def load_aws_secrets(secret_id: str, region: str = "us-east-1") -> dict[str, str]:
    client = boto3.client("secretsmanager", region_name=region)
    raw = client.get_secret_value(SecretId=secret_id)["SecretString"]
    return json.loads(raw)


def hydrate_env_from_aws() -> None:
    import os
    if os.getenv("ENV") in {"staging", "prod"}:
        for k, v in load_aws_secrets(f"erp-api/{os.environ['ENV']}").items():
            os.environ.setdefault(k, v)
```

Call `hydrate_env_from_aws()` **before** instantiating `Settings()` in `main.py`.

### HashiCorp Vault

```python
import hvac

def load_vault_secrets(path: str) -> dict[str, str]:
    client = hvac.Client(url=settings.VAULT_ADDR, token=settings.VAULT_TOKEN.get_secret_value())
    return client.secrets.kv.v2.read_secret_version(path=path)["data"]["data"]
```

### Doppler / 1Password

Both inject env vars before the app starts (`doppler run -- uvicorn ...`). No code change needed — the typed `Settings` still validates them.

---

## Secret Rotation

Long-running app + rotated secret = stale value in memory. Two approaches:

**1. Restart on rotation** (simplest, recommended):
- Vault webhook → ECS/K8s rolling restart → app re-reads secrets at boot.

**2. Periodic refresh** (only if you can't restart):
```python
# app/config/refresh.py
import asyncio
from app.config.settings import get_settings

async def refresh_settings_loop(interval_seconds: int = 300) -> None:
    while True:
        await asyncio.sleep(interval_seconds)
        get_settings.cache_clear()  # next call rebuilds
```
Register as a startup task. Code paths must call `get_settings()` each request, not import `settings` once.

---

## Safe Logging — Redact Always

```python
# app/utils/redact.py
SENSITIVE_KEYS = {"password", "token", "secret", "authorization", "api_key", "jwt"}

def redact(d: dict) -> dict:
    return {k: ("***" if k.lower() in SENSITIVE_KEYS else v) for k, v in d.items()}
```

In `fastapi-logging` middleware, run `redact()` on headers and bodies before logging.

Pydantic `SecretStr` already redacts in tracebacks. Combine both layers.

---

## Validation at Startup (Fail-Fast)

`Settings()` raises `ValidationError` if any required var is missing or wrong type. Let it crash — don't catch.

```python
# app/main.py
from app.config.settings import settings  # raises here if misconfigured
```

Container orchestrators (K8s, ECS) will refuse to mark the pod ready, preventing a bad deploy from serving traffic.

---

## .env.example Template

Always commit a complete example so new devs know every required var:

```dotenv
# .env.example
ENV=local
DEBUG=true
LOG_LEVEL=DEBUG

DATABASE_URL=postgresql+asyncpg://erp:erp@localhost:5432/erp
DATABASE_POOL_SIZE=10
DATABASE_MAX_OVERFLOW=20

REDIS_URL=redis://localhost:6379/0

JWT_SECRET=change-me-to-a-32-char-random-string-xx
JWT_ALGORITHM=HS256
ACCESS_TOKEN_TTL_MINUTES=15
REFRESH_TOKEN_TTL_DAYS=7

STRIPE_API_KEY=
SENTRY_DSN=
```

---

## Anti-patterns

| Don't | Why |
|------|-----|
| `os.getenv("FOO")` scattered across code | No type safety, no validation, no central docs |
| `JWT_SECRET: str` (plain str) | Leaks in logs/tracebacks; use `SecretStr` |
| Committing real `.env` | Single biggest cause of credential leaks |
| Wrapping `Settings()` in try/except at startup | Hides misconfig, server boots broken |
| Different config classes per environment | Drift; use one class + env vars |
| Logging `settings` | Use `settings.model_dump(mode="json")` then `redact()` |

---

## Verification Checklist

- [ ] `Settings` raises on missing required vars (test with `monkeypatch.delenv`)
- [ ] All secrets typed `SecretStr`
- [ ] `.env*` ignored in `.gitignore`; `.env.example` committed and complete
- [ ] No `os.getenv` outside `app/config/`
- [ ] Logging middleware redacts sensitive headers/keys
- [ ] Prod uses a secret manager, not a `.env` file
- [ ] `make lint` / mypy passes with `--strict`
