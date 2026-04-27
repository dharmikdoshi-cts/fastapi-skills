---
name: fastapi-audit-trail
description: >
  Implement audit trails and change tracking for ERP/financial FastAPI apps:
  who-did-what-when tables, before/after diffs via SQLAlchemy events, soft
  delete, immutable append-only ledger, request-context capture (user, IP,
  user-agent, request_id), tamper-evident hash chains, query/export APIs,
  and retention policy. Use this skill whenever the user asks about audit
  trail, audit log, change tracking, history, "who changed X", soft delete,
  ledger, immutability, or compliance/SOC2/SOX logging. Python 3.12+,
  SQLAlchemy 2.x async, contextvars.
---

# FastAPI Audit Trail Skill

Capture every meaningful change with full context. Required for ERP, finance, regulated systems. Python 3.12+.

---

## Decision: Three Patterns

| Pattern | Captures | Use when |
|---------|----------|----------|
| **Audit log table** (event-sourced view) | INSERT/UPDATE/DELETE per row | General CRUD audit |
| **Per-table history** (SCD-2-style) | Full row snapshot per change | Need to query historical state at a point in time |
| **Append-only ledger** | Domain events with hash chain | Financial transactions, must be tamper-evident |

ERPs typically use **audit log + ledger for money**. Don't try to build all three at once.

---

## Audit Log Schema

```python
# app/models/audit.py
from datetime import datetime
from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC), index=True)

    # Actor
    actor_user_id: Mapped[int | None] = mapped_column(index=True)
    actor_ip: Mapped[str | None] = mapped_column(String(45))
    actor_user_agent: Mapped[str | None] = mapped_column(String(255))

    # Request
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    tenant_id: Mapped[int | None] = mapped_column(index=True)

    # What changed
    entity_type: Mapped[str] = mapped_column(String(64), index=True)   # "Invoice"
    entity_id: Mapped[str] = mapped_column(String(64), index=True)     # "1234"
    action: Mapped[str] = mapped_column(String(16))                    # "create"|"update"|"delete"|"approve"|...
    changes: Mapped[dict | None] = mapped_column(JSON)                  # {"field": ["old", "new"]}
    metadata: Mapped[dict | None] = mapped_column(JSON)                 # extra context
```

Index `(entity_type, entity_id)` for "history of one record" queries, plus `(actor_user_id, occurred_at)` for "what did this user do."

---

## Request Context via ContextVar

Capture the actor without threading it through every function:

```python
# app/audit/context.py
from contextvars import ContextVar
from dataclasses import dataclass

@dataclass(frozen=True)
class AuditContext:
    actor_user_id: int | None
    actor_ip: str | None
    actor_user_agent: str | None
    request_id: str | None
    tenant_id: int | None

_audit_ctx: ContextVar[AuditContext | None] = ContextVar("audit_ctx", default=None)

def set_audit_context(ctx: AuditContext) -> None:
    _audit_ctx.set(ctx)

def get_audit_context() -> AuditContext | None:
    return _audit_ctx.get()
```

Set it in middleware:
```python
# app/middleware/audit_context.py
class AuditContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        user = getattr(request.state, "user", None)
        set_audit_context(AuditContext(
            actor_user_id=user.id if user else None,
            actor_ip=request.client.host if request.client else None,
            actor_user_agent=request.headers.get("user-agent", "")[:255],
            request_id=request.state.request_id,
            tenant_id=getattr(user, "tenant_id", None),
        ))
        return await call_next(request)
```

ContextVars are async-safe — they don't leak between concurrent requests.

---

## Auto-Capture via SQLAlchemy Events

```python
# app/audit/sqlalchemy_hook.py
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, UnitOfWork

AUDITED_MODELS = {Invoice, Customer, Order, Payment}  # opt-in
SKIP_FIELDS = {"updated_at", "search_tsv"}             # noisy

def diff_model(obj) -> dict | None:
    state = inspect(obj)
    changes = {}
    for attr in state.attrs:
        if attr.key in SKIP_FIELDS:
            continue
        hist = attr.history
        if hist.has_changes():
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            changes[attr.key] = [_jsonable(old), _jsonable(new)]
    return changes or None

@event.listens_for(Session, "before_flush")
def capture_changes(session, flush_context, instances):
    pending: list[AuditLog] = []
    ctx = get_audit_context()

    def make_log(obj, action, changes):
        return AuditLog(
            actor_user_id=ctx.actor_user_id if ctx else None,
            actor_ip=ctx.actor_ip if ctx else None,
            actor_user_agent=ctx.actor_user_agent if ctx else None,
            request_id=ctx.request_id if ctx else None,
            tenant_id=ctx.tenant_id if ctx else None,
            entity_type=obj.__class__.__name__,
            entity_id=str(getattr(obj, "id", "")),
            action=action,
            changes=changes,
        )

    for obj in session.new:
        if type(obj) in AUDITED_MODELS:
            pending.append(make_log(obj, "create", _row_snapshot(obj)))
    for obj in session.dirty:
        if type(obj) in AUDITED_MODELS:
            d = diff_model(obj)
            if d:
                pending.append(make_log(obj, "update", d))
    for obj in session.deleted:
        if type(obj) in AUDITED_MODELS:
            pending.append(make_log(obj, "delete", _row_snapshot(obj)))

    for log in pending:
        session.add(log)
```

Audit rows commit in the **same transaction** as the change. If the change rolls back, so does the audit.

---

## Custom Domain Events (Beyond CRUD)

CRUD-only audit misses the *meaning* of business actions. Capture explicit events:

```python
# In service:
async def approve_invoice(invoice_id: int, *, approver: User):
    invoice = await repo.get(invoice_id)
    if invoice.status != "draft":
        raise InvalidState("only draft invoices can be approved")
    invoice.status = "approved"
    invoice.approved_by_id = approver.id

    session.add(AuditLog(
        entity_type="Invoice", entity_id=str(invoice.id),
        action="approve",
        actor_user_id=approver.id,
        metadata={"previous_status": "draft", "new_status": "approved"},
    ))
```

"Approval" is more meaningful than "status went from 'draft' to 'approved'."

---

## Soft Delete

Don't `DELETE` rows for entities that may need to be referenced historically:

```python
class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, index=True)
    deleted_by_id: Mapped[int | None] = mapped_column(default=None)

    @hybrid_property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None
```

Default queries should hide deleted rows. Use a global filter:

```python
@event.listens_for(Session, "do_orm_execute")
def soft_delete_filter(execute_state):
    if execute_state.is_select and not execute_state.execution_options.get("include_deleted"):
        execute_state.statement = execute_state.statement.options(
            with_loader_criteria(SoftDeleteMixin, lambda cls: cls.deleted_at.is_(None))
        )
```

For hard-delete cases (GDPR right-to-erasure), document the override path explicitly.

---

## Append-Only Ledger (Money)

For financial events, **never UPDATE**. Append events; project current state from them.

```python
class LedgerEntry(Base):
    __tablename__ = "ledger"
    id: Mapped[int] = mapped_column(primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    account_id: Mapped[int] = mapped_column(index=True)
    amount_cents: Mapped[int]              # signed: + credit, - debit
    currency: Mapped[str] = mapped_column(String(3))
    reference_type: Mapped[str]            # "Invoice"
    reference_id: Mapped[str]
    actor_user_id: Mapped[int | None]
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)

    __table_args__ = (
        # No UPDATE/DELETE permission for app role:
        # GRANT INSERT, SELECT ON ledger TO erp_app_role;
        # REVOKE UPDATE, DELETE ON ledger FROM erp_app_role;
    )
```

### Hash chain (tamper-evident)

```python
import hashlib, json

def compute_hash(entry: LedgerEntry, prev_hash: str) -> str:
    body = {
        "occurred_at": entry.occurred_at.isoformat(),
        "account_id": entry.account_id,
        "amount_cents": entry.amount_cents,
        "currency": entry.currency,
        "reference": (entry.reference_type, entry.reference_id),
        "actor": entry.actor_user_id,
        "prev_hash": prev_hash,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
```

On append: read latest entry's hash → compute new hash → insert. Any tamper breaks the chain. Run a daily verification job.

Database-level enforcement: revoke UPDATE/DELETE from the app role; only a separate, restricted operator can correct via reversing entries.

---

## Audit-Log API

```python
@router.get("/audit", dependencies=[Depends(require_role("auditor"))])
async def list_audit(
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor_user_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    page: PageParams = Depends(),
):
    return await audit_repo.list(...)
```

- Auditor role required (read access ≠ write access)
- Always paginated
- Export CSV/NDJSON for compliance asks

---

## Retention

Audit data grows fast. Design retention up front:

| Data | Retention | Why |
|------|-----------|-----|
| CRUD audit log (UI actions) | 1-2 years online, 7 years cold storage | Tradeoff cost vs compliance |
| Auth events (login, logout, mfa) | 90 days online, 1 year cold | Security investigation window |
| Ledger | **Forever** (or per regulator) | Financial records |

Move old rows to S3/Glacier (one Parquet file per month). Keep an index of what's archived.

---

## What NOT to Audit

- Read-only queries (huge volume, low value)
- Health checks / metrics endpoints
- Internal background jobs that don't change state
- Field-level changes to non-business fields (`updated_at`, search vectors)

Audit fatigue is real. Auditing everything = auditing nothing.

---

## Anti-patterns

| Don't | Why |
|------|-----|
| Audit log in a separate DB | Loses transactional consistency |
| Hard-delete from audit log | Defeats the purpose; archive instead |
| Store full row snapshots for every UPDATE | Bloats; store diff |
| Capture passwords / tokens / PII in `changes` | Catastrophic leak surface |
| Mutate ledger entries | Append correction entries instead |
| Omit `request_id` and `actor_ip` | Investigations stall without them |
| Audit at HTTP middleware level | Misses background jobs and CLI scripts |

---

## Verification Checklist

- [ ] `AuditContext` set in middleware AND for background jobs/CLI
- [ ] Audit rows commit in same transaction as the change
- [ ] Sensitive fields excluded from `changes` JSON
- [ ] Soft-delete filter applied by default; opt-in to include
- [ ] Ledger role lacks UPDATE/DELETE at DB level
- [ ] Hash-chain verification job scheduled daily
- [ ] Audit-log read endpoint requires auditor role
- [ ] Retention/archival policy documented and automated
- [ ] Tests: create/update/delete each emit one audit row with correct actor, IP, request_id
