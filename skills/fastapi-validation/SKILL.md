---
name: fastapi-validation
description: >
  Implement input validation for FastAPI using Pydantic v2: field constraints,
  custom types (EmailStr, AnyUrl, conint, constr), field/model validators,
  reusable validators with Annotated, sanitization (HTML escape, strip, lower),
  cross-field rules, custom error messages, and reusable type aliases for ERP
  domains (Money, ISODate, NonEmptyStr, PositiveInt). Use this skill whenever
  the user asks about input validation, Pydantic validators, field_validator,
  model_validator, custom types, sanitization, "how to validate X", or
  validation error messages. Python 3.12+, Pydantic v2.
---

# FastAPI Validation Skill

Pydantic v2 validation, sanitization, and reusable typed primitives. Python 3.12+.

---

## Layered Validation Strategy

```
HTTP request
    │
    ▼
[1] Type/shape    ── Pydantic schema, fail-fast 422
    │
    ▼
[2] Field rules   ── Field(..., gt=0, max_length=200), constrained types
    │
    ▼
[3] Cross-field   ── @model_validator: e.g. start_date < end_date
    │
    ▼
[4] Business rule ── In service layer (uniqueness, FK existence, balances)
    │
    ▼
Repository
```

Don't push business rules into Pydantic. Pydantic = shape + format. Service = domain rules.

---

## Field Constraints

```python
from typing import Annotated
from pydantic import BaseModel, EmailStr, Field, AnyUrl

class UserCreate(BaseModel):
    email: EmailStr
    username: Annotated[str, Field(min_length=3, max_length=32, pattern=r"^[a-z0-9_]+$")]
    age: Annotated[int, Field(ge=18, le=120)]
    website: AnyUrl | None = None
    tags: Annotated[list[str], Field(max_length=10)]
```

`Annotated[T, Field(...)]` is preferred over `field: T = Field(...)` — composes cleanly with `Depends()` and reusable types.

---

## Reusable Type Aliases (ERP domain)

```python
# app/schemas/types.py
from decimal import Decimal
from datetime import date
from typing import Annotated
from pydantic import Field, AfterValidator, StringConstraints

NonEmptyStr   = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
ShortStr      = Annotated[str, StringConstraints(min_length=1, max_length=255, strip_whitespace=True)]
PositiveInt   = Annotated[int, Field(gt=0)]
NonNegativeInt = Annotated[int, Field(ge=0)]
Money         = Annotated[Decimal, Field(max_digits=14, decimal_places=2, ge=0)]
Percent       = Annotated[Decimal, Field(max_digits=5, decimal_places=2, ge=0, le=100)]

def _no_future(d: date) -> date:
    if d > date.today():
        raise ValueError("date cannot be in the future")
    return d

PastOrTodayDate = Annotated[date, AfterValidator(_no_future)]
```

Then schemas read like a domain dictionary:

```python
class InvoiceCreate(BaseModel):
    customer_name: ShortStr
    amount: Money
    tax_percent: Percent
    issue_date: PastOrTodayDate
```

---

## Field Validators

```python
from pydantic import BaseModel, field_validator

class ProductCreate(BaseModel):
    sku: str
    name: str

    @field_validator("sku")
    @classmethod
    def sku_format(cls, v: str) -> str:
        v = v.strip().upper()
        if not v.startswith("SKU-"):
            raise ValueError("must start with 'SKU-'")
        return v

    @field_validator("name")
    @classmethod
    def name_clean(cls, v: str) -> str:
        return " ".join(v.split())  # collapse whitespace
```

Always `@classmethod`. Always return the (possibly transformed) value.

---

## Model Validators (cross-field)

```python
from pydantic import BaseModel, model_validator
from datetime import date
from typing import Self

class DateRange(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def check_order(self) -> Self:
        if self.start > self.end:
            raise ValueError("start must be on or before end")
        return self
```

`mode="after"` = fields already typed. `mode="before"` = raw input dict, use sparingly.

---

## Sanitization

Validation rejects bad input. Sanitization cleans accepted input. Both happen in Pydantic.

```python
from html import escape
from typing import Annotated
from pydantic import AfterValidator, BaseModel, StringConstraints

def html_escape(v: str) -> str:
    return escape(v)

SafeText = Annotated[
    str,
    StringConstraints(min_length=1, max_length=5000, strip_whitespace=True),
    AfterValidator(html_escape),
]

class CommentCreate(BaseModel):
    body: SafeText
```

For richer sanitization (allowed tags), use `bleach` in an `AfterValidator`.

---

## Custom Error Messages

Pydantic v2 errors are structured (`loc`, `msg`, `type`, `input`). Hand them off to your `fastapi-exception` handler so the FE-friendly response is consistent.

To customize the `msg`:
```python
@field_validator("password")
@classmethod
def strong(cls, v: str) -> str:
    if len(v) < 12:
        raise ValueError("Password must be at least 12 characters.")
    if not any(c.isdigit() for c in v):
        raise ValueError("Password must contain at least one number.")
    return v
```

Don't override the global error format here — that's the exception handler's job.

---

## Optional vs Nullable vs Missing

Pydantic v2 distinguishes:

| Declaration | Allowed values |
|---|---|
| `x: int` | int only — required |
| `x: int \| None` | int or null — required |
| `x: int = 0` | int, default 0 — optional |
| `x: int \| None = None` | int, null, or omitted |

In APIs, prefer **explicit `None`** over "missing" for partial updates; combine with `model_dump(exclude_unset=True)` for PATCH semantics.

---

## PATCH Semantics

```python
class UserPatch(BaseModel):
    email: EmailStr | None = None
    name: NonEmptyStr | None = None
    model_config = {"extra": "forbid"}

# Service layer:
patch = payload.model_dump(exclude_unset=True)
for k, v in patch.items():
    setattr(user, k, v)
```

`exclude_unset=True` is the magic — only fields the client actually sent.

---

## Strict Mode

```python
from pydantic import BaseModel, ConfigDict

class Strict(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", str_strip_whitespace=True)
```

Use for inbound API schemas. Lax mode (default) is fine for outbound responses.

---

## Validating Query / Path / Header

```python
from typing import Annotated
from fastapi import Query, Path, Header

@router.get("/users/{user_id}")
async def get_user(
    user_id: Annotated[int, Path(ge=1)],
    include: Annotated[list[str] | None, Query(max_length=5)] = None,
    x_request_id: Annotated[str | None, Header()] = None,
): ...
```

---

## Anti-patterns

| Don't | Why |
|------|-----|
| Validate uniqueness in Pydantic | Pydantic is sync + can't see DB |
| Use `regex=` (deprecated) | Use `pattern=` in v2 |
| Catch `ValidationError` and reformat | Let global handler do it (consistent FE shape) |
| `Any` to silence pyright | Defeats the point — write a proper type |
| Mutate `cls` in validator | Validators are pure functions |
| Trust client-supplied `id` on create | Generate server-side |

---

## Verification Checklist

- [ ] All inbound schemas use `extra="forbid"`
- [ ] Reusable types live in `app/schemas/types.py`
- [ ] No business rules inside Pydantic validators
- [ ] PATCH endpoints use `exclude_unset=True`
- [ ] HTML/free-text fields run through `AfterValidator` sanitizer
- [ ] mypy/pyright strict passes on schemas
- [ ] Validation errors flow through global exception handler
