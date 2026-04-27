---
name: fastapi-openapi-docs
description: >
  Customize and harden FastAPI's auto-generated OpenAPI/Swagger docs: tag
  organization, operation IDs, response examples, request examples, security
  schemes, server URLs per environment, deprecation metadata, hiding internal
  endpoints, generating typed clients (TS/Python) from the schema, exporting
  static OpenAPI JSON for CI, and protecting docs in production. Use this
  skill whenever the user asks about Swagger, OpenAPI, ReDoc, /docs, schema
  examples, operation_id, tags, generating a client, or "documenting the API".
  Python 3.12+, FastAPI 0.110+.
---

# FastAPI OpenAPI / Docs Skill

Production-grade API docs: organized, exampled, securable, client-generatable.

---

## Goals

- `/docs` is reviewable by FE engineers without prose docs.
- Operation IDs are stable → generated TS clients have clean method names.
- Examples cover happy path + 1-2 error cases per endpoint.
- Internal/admin routes don't leak in public schema.
- Schema is exportable for contract tests + client codegen in CI.

---

## App-Level Metadata

```python
# app/main.py
from fastapi import FastAPI
from app.config.settings import settings

app = FastAPI(
    title="ERP API",
    description=open("docs/api-overview.md").read(),
    version="2025.04.27",                 # CalVer is friendly for ERP
    contact={"name": "Platform Team", "email": "platform@comprint.com"},
    license_info={"name": "Proprietary"},
    docs_url="/docs" if settings.ENV != "prod" else None,
    redoc_url="/redoc" if settings.ENV != "prod" else None,
    openapi_url="/openapi.json" if settings.ENV != "prod" else None,
    servers=[
        {"url": "https://api.comprint.com", "description": "Production"},
        {"url": "https://api.staging.comprint.com", "description": "Staging"},
        {"url": "http://localhost:8000", "description": "Local"},
    ],
    swagger_ui_parameters={"defaultModelsExpandDepth": -1, "displayRequestDuration": True},
)
```

In prod, hide docs by default; expose behind auth if needed (see "Protecting Docs").

---

## Tags + Tag Metadata

```python
tags_metadata = [
    {"name": "auth", "description": "Login, token refresh, password reset."},
    {"name": "users", "description": "User CRUD and profile management."},
    {"name": "invoices", "description": "Invoice issuance and payment tracking.",
     "externalDocs": {"description": "Invoice spec", "url": "https://docs/.../invoices"}},
]

app = FastAPI(..., openapi_tags=tags_metadata)
```

In each router:
```python
router = APIRouter(prefix="/v1/invoices", tags=["invoices"])
```

One tag per router. Don't tag a single endpoint with three tags.

---

## Stable Operation IDs (for codegen)

By default FastAPI uses `function_name_path_method`. Override for clean client SDKs:

```python
def custom_unique_id(route: "APIRoute") -> str:
    # invoices_list, invoices_create, invoices_get, ...
    return f"{route.tags[0]}_{route.name}" if route.tags else route.name

app = FastAPI(..., generate_unique_id_function=custom_unique_id)
```

Or per-route:
```python
@router.get("", operation_id="invoices_list")
```

**Why it matters:** TS codegen produces `apiClient.invoices.list()` instead of `apiClient.invoices.listInvoicesV1InvoicesGet()`.

---

## Examples on Schemas

```python
from pydantic import BaseModel, Field

class InvoiceCreate(BaseModel):
    customer_id: int = Field(..., examples=[42])
    amount: Decimal = Field(..., examples=["1250.00"])
    due_date: date = Field(..., examples=["2026-05-15"])

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "customer_id": 42,
                    "amount": "1250.00",
                    "due_date": "2026-05-15"
                }
            ]
        }
    }
```

For multi-example bodies:

```python
from fastapi import Body

@router.post("")
async def create(
    payload: Annotated[InvoiceCreate, Body(openapi_examples={
        "standard": {
            "summary": "Standard invoice",
            "value": {"customer_id": 42, "amount": "1250.00", "due_date": "2026-05-15"},
        },
        "credit_note": {
            "summary": "Negative amount (credit)",
            "value": {"customer_id": 42, "amount": "-100.00", "due_date": "2026-05-15"},
        },
    })],
): ...
```

---

## Response Documentation

Always declare every status code your endpoint can return:

```python
from app.schemas.errors import ErrorResponse

@router.post(
    "",
    response_model=Page[InvoiceOut],
    status_code=201,
    responses={
        400: {"model": ErrorResponse, "description": "Validation failed"},
        401: {"model": ErrorResponse, "description": "Not authenticated"},
        403: {"model": ErrorResponse, "description": "Missing scope"},
        409: {"model": ErrorResponse, "description": "Duplicate invoice"},
        422: {"model": ErrorResponse, "description": "Schema invalid"},
    },
)
async def create_invoice(...): ...
```

Centralize the boilerplate:

```python
# app/api/responses.py
COMMON_ERRORS = {
    401: {"model": ErrorResponse, "description": "Unauthenticated"},
    403: {"model": ErrorResponse, "description": "Forbidden"},
    422: {"model": ErrorResponse, "description": "Validation error"},
    500: {"model": ErrorResponse, "description": "Internal error"},
}
```

Use `responses={**COMMON_ERRORS, 409: {...}}`.

---

## Security Schemes

```python
from fastapi.security import OAuth2PasswordBearer, APIKeyHeader

oauth2 = OAuth2PasswordBearer(tokenUrl="/v1/auth/login")
api_key = APIKeyHeader(name="X-API-Key")
```

Declare them on the dependency, FastAPI auto-wires the `securitySchemes` block. The "Authorize" button in `/docs` then works.

---

## Hiding Internal Endpoints

```python
@router.get("/_internal/cache/flush", include_in_schema=False)
async def flush_cache(): ...
```

For an entire admin router:
```python
admin_router = APIRouter(prefix="/admin", include_in_schema=False)
```

Even hidden, **enforce auth** — `include_in_schema=False` is documentation-only, not security.

---

## Deprecation

```python
@router.get("/users/me", deprecated=True, summary="Use /v2/users/me")
async def me_v1(): ...
```

Combine with the sunset header pattern from `fastapi-api-design`.

---

## Protecting Docs in Production

Pattern A — hide entirely:
```python
app = FastAPI(..., docs_url=None, redoc_url=None, openapi_url=None)
```

Pattern B — auth-gated docs:
```python
from fastapi import Depends, FastAPI
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

@app.get("/openapi.json", include_in_schema=False)
async def openapi(user: Annotated[User, Depends(require_admin)]):
    return get_openapi(title=app.title, version=app.version, routes=app.routes)

@app.get("/docs", include_in_schema=False)
async def docs(user: Annotated[User, Depends(require_admin)]):
    return get_swagger_ui_html(openapi_url="/openapi.json", title="API Docs")
```

Pattern C — basic-auth in front of docs (good for staging) via middleware.

---

## Exporting Schema for CI / Client Codegen

```python
# scripts/export_openapi.py
import json
from app.main import app

with open("openapi.json", "w") as f:
    json.dump(app.openapi(), f, indent=2)
```

Run in CI:
```bash
python scripts/export_openapi.py
# Diff vs main; fail PR if breaking changes without version bump
oasdiff diff main.openapi.json openapi.json --fail-on ERR
```

Generate TS client:
```bash
npx openapi-typescript openapi.json -o frontend/src/api/schema.ts
# or
npx @hey-api/openapi-ts -i openapi.json -o frontend/src/api/client
```

Run codegen on every backend merge → FE picks up new types automatically.

---

## Schema Quality Lint Rules (CI)

Use [Spectral](https://stoplight.io/open-source/spectral) with a ruleset:
- Every operation has `summary`, `description`, `operationId`.
- Every 4xx/5xx response has a schema.
- All `requestBody` has at least one example.
- Operation IDs are unique and snake_case.

Block merges that regress these.

---

## Anti-patterns

| Don't | Why |
|------|-----|
| Default operation IDs in prod | Generated client method names are unreadable |
| Documenting only happy path | FE has no idea how to handle errors |
| Putting auth secrets in `servers` URL examples | They get copied into client code |
| Exposing `/docs` on prod with no auth | Leaks internal endpoint surface |
| Editing `app.openapi_schema` mutably without `app.openapi = lambda: ...` | Cache breaks |
| Big `description` strings inline in code | Move to markdown files, `open(...).read()` |
| Versioning by mutating same path | Breaks clients silently; use URL versioning |

---

## Verification Checklist

- [ ] Title, version, contact set
- [ ] All routers have exactly one tag with description
- [ ] Custom `generate_unique_id_function` set
- [ ] Each endpoint declares `responses=` for at least 401/403/422
- [ ] At least one `examples=` per request body
- [ ] `/docs` and `/openapi.json` hidden or auth-gated in prod
- [ ] CI exports `openapi.json` and runs Spectral + `oasdiff`
- [ ] FE/BE share the schema for codegen (no hand-written types)
