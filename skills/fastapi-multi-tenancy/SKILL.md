---
name: fastapi-multi-tenancy
description: >
  Implement multi-tenancy for FastAPI ERP/SaaS apps: choose between
  shared-schema (tenant_id column), schema-per-tenant, and database-per-tenant;
  enforce row-level isolation via SQLAlchemy session events and Postgres RLS;
  resolve tenant from JWT/subdomain/header; manage migrations across schemas;
  handle cross-tenant admin operations safely. Use this skill whenever the
  user asks about multi-tenant, multi-tenancy, tenant isolation, RLS,
  row-level security, schema-per-tenant, "SaaS architecture", "tenant_id",
  or how to scope data per customer. Python 3.12+, SQLAlchemy 2.x async,
  PostgreSQL.
---

# FastAPI Multi-Tenancy Skill

Three isolation patterns + enforcement mechanisms + tenant resolution. Python 3.12+, PostgreSQL.

---

## Decision Matrix

| Pattern | Isolation | Cost / tenant | Operational complexity | When to use |
|---------|-----------|---------------|------------------------|-------------|
| **Shared schema** (`tenant_id` column) | Logical (app+RLS) | Cheapest | Low | 100s–10k+ tenants, similar usage profiles |
| **Schema-per-tenant** | Physical (DB schemas) | Medium | Medium | 10s–100s tenants, regulatory pressure, per-tenant customization |
| **Database-per-tenant** | Strongest | Highest | High | Few enterprise tenants, strict data residency, noisy neighbors |

**ERP default: shared schema + Postgres RLS.** Easiest to operate, scales high, isolation strong if RLS is enforced.

---

## Pattern 1: Shared Schema with Postgres RLS

### Schema convention

Every tenanted table has `tenant_id`:

```python
class TenantMixin:
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), index=True, nullable=False)

class Invoice(Base, TenantMixin):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(primary_key=True)
    ...
```

Index `(tenant_id, id)` and `(tenant_id, <common filter>)` on tenanted tables. Almost every query starts with `WHERE tenant_id = :t`.

### RLS at the database

Application bugs happen. RLS is the safety net:

```sql
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON invoices
  USING (tenant_id = current_setting('app.tenant_id')::bigint);
```

Set the GUC at the start of each transaction:

```python
# app/db/tenant_session.py
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

@event.listens_for(AsyncSession.sync_session_class, "after_begin")
def set_tenant_guc(session, transaction, connection):
    ctx = get_audit_context()  # or a dedicated tenant context var
    if ctx and ctx.tenant_id is not None:
        connection.execute(text("SET LOCAL app.tenant_id = :tid"), {"tid": ctx.tenant_id})
```

`SET LOCAL` is transaction-scoped and resets automatically. Even if the ORM forgets `WHERE tenant_id`, RLS blocks cross-tenant rows.

### Defense in depth — also filter in the ORM

```python
# app/db/tenant_filter.py
from sqlalchemy import event
from sqlalchemy.orm import with_loader_criteria, Session

@event.listens_for(Session, "do_orm_execute")
def tenant_filter(execute_state):
    if execute_state.is_select and not execute_state.execution_options.get("skip_tenant_filter"):
        ctx = get_audit_context()
        if ctx and ctx.tenant_id is not None:
            execute_state.statement = execute_state.statement.options(
                with_loader_criteria(
                    TenantMixin,
                    lambda cls: cls.tenant_id == ctx.tenant_id,
                    include_aliases=True,
                )
            )
```

Both layers (RLS + ORM filter) run. Bug in one is caught by the other.

### Admin / cross-tenant queries

Sometimes you legitimately need to query across tenants (admin dashboard, support tooling):

```python
result = await session.execute(stmt, execution_options={"skip_tenant_filter": True})
```

And bypass RLS by connecting as a superuser role *only* from a separate "admin" connection pool — never from request handlers. Audit every cross-tenant query.

---

## Pattern 2: Schema-per-Tenant

One PostgreSQL schema (`tenant_42`) per tenant, identical structure.

```python
from sqlalchemy import event

@event.listens_for(AsyncSession.sync_session_class, "after_begin")
def set_search_path(session, transaction, connection):
    ctx = get_tenant_context()
    if ctx:
        connection.execute(text(f'SET LOCAL search_path TO "tenant_{ctx.tenant_id}", public'))
```

Pros: clean isolation, easy per-tenant backup/export, per-tenant migrations possible.
Cons: connection pool churn, migration fan-out (`alembic upgrade head` per schema), join across tenants impossible.

### Migrations

```python
# alembic/env.py
def run_migrations_online():
    with engine.connect() as connection:
        for schema in list_tenant_schemas(connection):
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                version_table_schema=schema,
                include_schemas=False,
            )
            connection.execute(text(f'SET search_path TO "{schema}"'))
            with context.begin_transaction():
                context.run_migrations()
```

Run migrations **per schema** in CI. New tenants are provisioned via a "create tenant" job that copies the latest schema template.

---

## Pattern 3: Database-per-Tenant

One database per tenant. Strongest isolation, highest cost.

```python
# app/db/tenant_engines.py
from functools import lru_cache
from sqlalchemy.ext.asyncio import create_async_engine

@lru_cache(maxsize=128)
def get_engine_for(tenant_id: int) -> AsyncEngine:
    cfg = lookup_tenant_db_config(tenant_id)  # from a tenant-registry DB
    return create_async_engine(cfg.url, pool_size=5, max_overflow=5)
```

A small "tenant registry" DB stores the connection string for each tenant.

Pros: hard isolation, per-tenant performance, easy regional pinning.
Cons: 1000 tenants → 1000 pools → memory pressure; migrations across all DBs; backups expand.

Use only when justified by compliance, residency, or noisy-neighbor concerns. Don't choose this by default.

---

## Tenant Resolution

Where does the request's tenant come from?

| Source | When | Notes |
|--------|------|-------|
| **JWT claim** | API authenticated by token | Most common; tenant baked into token at login |
| **Subdomain** | Browser SPA, e.g. `acme.app.com` | Friendly UX; resolve in middleware |
| **Header** | Service-to-service | `X-Tenant-Id`, only trust internal callers |
| **Path** | `/v1/tenants/{tenant_id}/...` | Avoid — couples API surface to tenancy model |

JWT-first, subdomain second. Never trust a client-supplied `tenant_id` body field.

```python
# app/middleware/tenant.py
async def resolve_tenant(request: Request) -> Tenant:
    user = request.state.user
    host_tenant = parse_subdomain(request.url.hostname)
    if host_tenant and host_tenant != user.tenant.slug:
        raise HTTPException(403, "Tenant mismatch")
    return user.tenant
```

Validate the JWT tenant matches the subdomain. Belt and braces.

---

## Authorization Rules

Tenant scoping ≠ authorization. A user inside a tenant still needs role checks.

```
isolation: which tenant's rows are visible
authorization: what this user can do with their tenant's rows
```

Both layers always run. Don't conflate.

---

## Common Foot-Guns

### 1. Background jobs without tenant context

Celery task receives only the task args. Forgetting `tenant_id` means the worker queries with no filter → potential leak.

```python
@shared_task
def issue_invoice_task(invoice_id: int, tenant_id: int):
    set_audit_context(AuditContext(tenant_id=tenant_id, ...))
    with SessionLocal() as session:  # GUC set via after_begin
        ...
```

Make `tenant_id` a required argument on every tenanted task.

### 2. Cross-tenant FK leaks

Foreign key referenced from another tenant's row. Add a **composite FK** that includes `tenant_id`:

```python
__table_args__ = (
    ForeignKeyConstraint(
        ["customer_id", "tenant_id"],
        ["customers.id", "customers.tenant_id"],
    ),
)
```

Now Postgres rejects a child row whose `(customer_id, tenant_id)` doesn't match a customer in the same tenant.

### 3. Migrations forgot RLS

Newly-added tenanted table without `ENABLE ROW LEVEL SECURITY` is a silent leak. Lint the schema in CI:

```sql
SELECT c.relname FROM pg_class c
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relrowsecurity = false
  AND c.relname IN (SELECT table_name FROM tenanted_tables);
```

Fail CI if non-empty.

### 4. Connection pool reuse leaks GUC

`SET` (without `LOCAL`) persists per connection. Rule: only ever use `SET LOCAL` inside a transaction.

### 5. `SELECT pg_sleep(...)` from one tenant blocks another

Long queries on shared schema starve others. Set `statement_timeout` per session and have admin tooling that can identify tenant by `app.tenant_id` GUC.

---

## Observability per Tenant

Tag metrics, logs, and traces with `tenant_id` (low cardinality) — but **never** with personally identifiable data.

```python
INVOICES_ISSUED.labels(tenant_id=str(tenant.id)).inc()
log_extra["tenant_id"] = tenant.id
span.set_attribute("tenant.id", tenant.id)
```

Per-tenant dashboards make "tenant X is slow" diagnoseable.

---

## Anti-patterns

| Don't | Why |
|------|-----|
| Trust client-supplied `tenant_id` | Trivially bypassed; always derive from auth |
| Skip RLS because "the ORM filters it" | One missed WHERE = data leak |
| Use `SET` (not `SET LOCAL`) for tenant GUC | Leaks across pooled connections |
| Run a single migration touching all tenants without canary | One broken migration = global outage |
| Cross-tenant joins in app code | Either go DB-per-tenant or do it in a separate analytics warehouse |
| Generate IDs not scoped to tenant | Don't expose globally-unique IDs that imply ordering |
| Same JWT signing key across tenants for SSO | Compromise blast radius = all tenants |

---

## Verification Checklist

- [ ] Decision (shared / schema / db) documented with rationale
- [ ] All tenanted tables have `tenant_id` + index + RLS policy
- [ ] `SET LOCAL app.tenant_id` runs in `after_begin` for every session
- [ ] ORM filter as defense-in-depth alongside RLS
- [ ] CI lint: every tenanted table has RLS enabled
- [ ] Composite `(id, tenant_id)` FKs prevent cross-tenant references
- [ ] Background jobs require `tenant_id` argument; context set on entry
- [ ] Admin/superuser pool separate from request pool; usage audited
- [ ] Tests: cross-tenant access returns 0 rows under both ORM filter and RLS, even with raw SQL
