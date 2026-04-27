---
name: fastapi-pagination-filtering
description: >
  Implement pagination, filtering, sorting, and search for FastAPI endpoints:
  offset/limit and cursor-based pagination, allow-listed sortable fields,
  filter DSL with Pydantic, full-text search hooks, and FE-friendly paginated
  response envelope (items, page, size, total, has_next). Use this skill
  whenever the user asks about pagination, list endpoints, "how to paginate",
  cursor pagination, sort, filter, search, query params for lists, or large
  result sets. Python 3.12+, SQLAlchemy 2.x async.
---

# FastAPI Pagination & Filtering Skill

Consistent list endpoints: paginate, filter, sort, search. Python 3.12+.

---

## Decision: Offset vs Cursor

| Pattern | Best for | Tradeoffs |
|---------|----------|-----------|
| **Offset/limit** | Admin tables, jump-to-page UIs | Slow on large offsets; counts double-up DB cost |
| **Cursor (keyset)** | Feeds, infinite scroll, large datasets | No "page 47", but stable + fast |

ERP rule: small reference tables (< 50k rows) → offset. Transactional tables (orders, ledger entries) → cursor.

---

## FE-Friendly Paginated Envelope

```json
{
  "success": true,
  "code": 200,
  "message": "OK",
  "data": {
    "items": [...],
    "pagination": {
      "page": 2,
      "size": 20,
      "total": 247,
      "total_pages": 13,
      "has_next": true,
      "has_prev": true
    }
  },
  "errors": null
}
```

For cursor:
```json
"pagination": { "size": 20, "next_cursor": "eyJpZCI6MTIzfQ==", "has_next": true }
```

Pick one shape per endpoint and stick to it.

---

## Reusable Pagination Schema

```python
# app/schemas/pagination.py
from typing import Annotated, Generic, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")

class PageParams(BaseModel):
    page: Annotated[int, Field(ge=1)] = 1
    size: Annotated[int, Field(ge=1, le=100)] = 20

class CursorParams(BaseModel):
    cursor: str | None = None
    size: Annotated[int, Field(ge=1, le=100)] = 20

class PageMeta(BaseModel):
    page: int
    size: int
    total: int
    total_pages: int
    has_next: bool
    has_prev: bool

class CursorMeta(BaseModel):
    size: int
    next_cursor: str | None
    has_next: bool

class Page(BaseModel, Generic[T]):
    items: list[T]
    pagination: PageMeta

class CursorPage(BaseModel, Generic[T]):
    items: list[T]
    pagination: CursorMeta
```

---

## Offset/Limit Implementation

```python
# app/repositories/base.py
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

async def paginate_offset(
    session: AsyncSession,
    stmt,                 # base select stmt (already filtered/sorted)
    *,
    page: int,
    size: int,
) -> tuple[list, int]:
    total = await session.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (await session.scalars(stmt.offset((page - 1) * size).limit(size))).all()
    return rows, total or 0
```

In endpoint:
```python
@router.get("", response_model=Page[UserOut])
async def list_users(params: Annotated[PageParams, Depends()], svc: ...):
    items, total = await svc.list(page=params.page, size=params.size)
    pages = (total + params.size - 1) // params.size
    return Page(
        items=items,
        pagination=PageMeta(
            page=params.page, size=params.size, total=total, total_pages=pages,
            has_next=params.page < pages, has_prev=params.page > 1,
        ),
    )
```

---

## Cursor (Keyset) Implementation

Encode the cursor (don't expose row IDs raw — clients shouldn't construct them):

```python
# app/utils/cursor.py
import base64, json

def encode_cursor(payload: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")

def decode_cursor(token: str) -> dict:
    pad = "=" * (-len(token) % 4)
    return json.loads(base64.urlsafe_b64decode(token + pad).decode())
```

Repository (newest-first by `(created_at, id)`):
```python
from sqlalchemy import and_, or_

async def list_after(
    session: AsyncSession, *, cursor: str | None, size: int
) -> tuple[list[Order], str | None]:
    stmt = select(Order).order_by(Order.created_at.desc(), Order.id.desc())
    if cursor:
        c = decode_cursor(cursor)
        stmt = stmt.where(
            or_(
                Order.created_at < c["ts"],
                and_(Order.created_at == c["ts"], Order.id < c["id"]),
            )
        )
    rows = (await session.scalars(stmt.limit(size + 1))).all()
    has_next = len(rows) > size
    rows = rows[:size]
    next_cur = encode_cursor({"ts": rows[-1].created_at.isoformat(), "id": rows[-1].id}) if has_next else None
    return rows, next_cur
```

Always order by a **unique tiebreaker** (`id`) alongside the sort key — otherwise rows duplicate or skip across pages.

---

## Sorting (Allow-list)

Never let the client send raw column names:

```python
ALLOWED_SORTS = {
    "created_at": Order.created_at,
    "amount": Order.amount,
    "status": Order.status,
}

class SortParams(BaseModel):
    sort: str = "created_at"
    order: Literal["asc", "desc"] = "desc"

def apply_sort(stmt, params: SortParams):
    col = ALLOWED_SORTS.get(params.sort)
    if col is None:
        raise HTTPException(422, f"sort '{params.sort}' not allowed")
    return stmt.order_by(col.asc() if params.order == "asc" else col.desc())
```

---

## Filtering DSL

Keep it simple — typed query params, not arbitrary expression languages.

```python
class OrderFilter(BaseModel):
    status: list[str] | None = None
    customer_id: int | None = None
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    q: str | None = None  # search

def apply_filter(stmt, f: OrderFilter):
    if f.status:
        stmt = stmt.where(Order.status.in_(f.status))
    if f.customer_id:
        stmt = stmt.where(Order.customer_id == f.customer_id)
    if f.min_amount is not None:
        stmt = stmt.where(Order.amount >= f.min_amount)
    if f.max_amount is not None:
        stmt = stmt.where(Order.amount <= f.max_amount)
    if f.created_from:
        stmt = stmt.where(Order.created_at >= f.created_from)
    if f.created_to:
        stmt = stmt.where(Order.created_at <= f.created_to)
    if f.q:
        stmt = stmt.where(Order.search_tsv.op("@@")(func.plainto_tsquery(f.q)))
    return stmt
```

In endpoint:
```python
@router.get("", response_model=Page[OrderOut])
async def list_orders(
    page: Annotated[PageParams, Depends()],
    sort: Annotated[SortParams, Depends()],
    filt: Annotated[OrderFilter, Depends()],
    svc: ...,
): ...
```

FastAPI maps each `BaseModel` to query params automatically when used with `Depends()`.

---

## Full-Text Search (Postgres)

Add a `tsvector` column + GIN index:

```sql
ALTER TABLE orders ADD COLUMN search_tsv tsvector
  GENERATED ALWAYS AS (
    to_tsvector('english', coalesce(reference, '') || ' ' || coalesce(notes, ''))
  ) STORED;

CREATE INDEX orders_search_idx ON orders USING gin(search_tsv);
```

Query: `Order.search_tsv.op("@@")(func.plainto_tsquery(q))`. For multi-word ranking, `ts_rank_cd`.

For richer needs (typo tolerance, synonyms): Meilisearch / Elasticsearch / Typesense — keep their results' IDs and re-hydrate from Postgres.

---

## Counting Costs (Offset Pagination)

`COUNT(*)` on large tables is expensive. Options:

1. **Approximate count** (Postgres `pg_class.reltuples`) for unfiltered lists.
2. **Cache total** for common filters (5-min TTL).
3. **Cursor pagination** — no count needed.
4. Exclude `total` for some endpoints; add a separate `/count` if FE needs it.

Don't recompute total on every page click of the same query — cache by filter hash.

---

## Anti-patterns

| Don't | Why |
|------|-----|
| `?sort=username; DROP TABLE` (raw column) | SQL injection, always allow-list |
| `OFFSET 1_000_000` in prod | Sequential scan; use cursor |
| Returning `total: -1` to mean "unknown" | Confusing; omit field or use a flag |
| Mixing offset and cursor on same endpoint | Confuses clients; pick one |
| Cursor without unique tiebreaker | Pages overlap or skip rows |
| Including PII in cursor token | Tokens leak in logs and history |
| `size=10000` allowed | DoS vector; cap at 100 |

---

## Verification Checklist

- [ ] All list endpoints return the same envelope shape
- [ ] `size` capped at 100; `page` validated `>= 1`
- [ ] Sort fields are allow-listed
- [ ] Filter schema typed, not free-form strings
- [ ] Cursor includes a unique tiebreaker
- [ ] Search uses indexed column (GIN/B-tree), not `ILIKE %x%`
- [ ] Tests cover: empty result, one page, last page, invalid sort, oversized size, malformed cursor
