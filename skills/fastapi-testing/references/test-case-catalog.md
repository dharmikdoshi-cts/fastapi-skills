# Per-Layer Test-Case Catalog

What tests **must** exist at each layer of a FastAPI project. Treat this as a checklist before declaring a feature done.

If a row says "must," there should be at least one test for it. "should" = strongly recommended.

---

## 1. Schema (Pydantic) — fast, no I/O

| Case | Level | Notes |
|------|-------|-------|
| Valid happy-path constructs | must | Smoke that the schema works |
| Each required field — missing → `ValidationError` | must | One test per required field |
| Each constraint (`min_length`, `ge`, `pattern`) — boundary above + below | must | Drive the constraints, not just defaults |
| `extra="forbid"` rejects unknown fields | must | If you've claimed strict mode |
| Custom `field_validator` accept + reject paths | must | Both branches |
| `model_validator` cross-field rule (e.g. start ≤ end) | must | |
| `EmailStr` / `AnyUrl` accept + reject | should | One per custom format |
| Sanitization (`AfterValidator`) actually transforms | must | Assert the output, not just no-throw |
| `model_dump(exclude_unset=True)` for PATCH only sends touched fields | must | |
| Serialization round-trip (`model_validate(model.model_dump())`) | should | Catches asymmetric coercions |

---

## 2. Repository — real DB, transactional rollback

Use a `session` fixture with `BEGIN` + `ROLLBACK` per test. Don't mock the DB.

| Case | Level | Notes |
|------|-------|-------|
| `create` returns persisted row with generated ID | must | |
| `get(missing_id)` returns `None` (or raises domain `NotFound`) | must | Pick one convention and stick to it |
| `update` modifies fields; `updated_at` advances | must | |
| `delete` removes row; subsequent `get` is None | must | Or soft-delete equivalent |
| `list` pagination — page boundaries, last page, empty | must | Three tests minimum |
| `list` with each filter applied independently | must | One per filter |
| `list` with combined filters | should | Common combos |
| Sort — each allow-listed sort key, asc + desc | should | |
| Unique constraint violation — domain exception, not raw `IntegrityError` | must | |
| FK violation — domain exception | must | |
| Concurrent update — optimistic locking (`version` column) raises | should | If using optimistic locking |
| Eager loading — `selectinload` actually loads relation | should | Catches N+1 |
| Multi-tenancy: query in tenant A returns 0 rows from tenant B (ORM + RLS) | must | Multi-tenant projects only |

---

## 3. Service / Use-Case — fake repo, no I/O

Use `FakeRepository` (Protocol-based, no mocking lib). Services contain business rules; this is where most logic lives.

| Case | Level | Notes |
|------|-------|-------|
| Happy path — given valid input, returns expected output | must | |
| Each branch / state transition | must | One test per branch — coverage tells you |
| Rule violation raises domain exception, not generic `ValueError` | must | E.g. `InvoiceAlreadyApproved` |
| Idempotency — repeating same op produces same state, no extra side effects | must | If endpoint is meant to be idempotent |
| Side effects fire (audit log, event published) on success only | must | Use a fake event bus |
| Side effects do NOT fire on failure (transaction rolled back) | must | |
| External dependency failure (e.g. payment provider 500) — wrapped/retried/surfaced correctly | must | Use a fake adapter |
| Authorization rule — actor without role → exception | must | Even if endpoint also checks; service is the source of truth |
| Time-dependent logic uses injectable clock | should | Frozen-time test |

---

## 4. API / Endpoint — TestClient + DI overrides

Integration tests with httpx `AsyncClient` against the app. Override DB session to use the test DB. Override auth to inject a known user.

| Case | Level | Notes |
|------|-------|-------|
| Success — correct status code, correct envelope shape | must | Validate `{success, code, message, data, errors}` |
| 400 / 422 — schema rejection per route | must | One missing field, one wrong type |
| 401 — missing/expired token | must | Both cases |
| 403 — authenticated but lacks role/scope | must | |
| 404 — entity not found | must | |
| 409 — unique constraint / state conflict | must | |
| 415 — wrong content type (file uploads / multipart) | should | Where applicable |
| 413 — payload too large | should | Upload endpoints |
| 429 — rate-limited (if rate limiting enabled) | should | |
| 500 — unhandled exception still returns FE-friendly envelope | must | One contrived failure |
| Pagination boundaries | must | First page, last page, empty |
| Filter combinations | should | At least one combined filter |
| Idempotency-Key honored | should | If the endpoint claims idempotency |
| CORS preflight allowed origin succeeds; disallowed denied | should | Once per app, not per endpoint |
| Response headers — `X-Request-Id`, `Sunset` (deprecated), cache headers | should | |
| OpenAPI schema includes the endpoint with documented responses | should | Contract test against `app.openapi()` |

---

## 5. Auth-Specific Tests

| Case | Level | Notes |
|------|-------|-------|
| Login with correct credentials returns access + refresh | must | |
| Login with wrong password — 401, no user enumeration leak | must | Same response for "wrong user" and "wrong password" |
| Expired access token — 401 | must | Tamper with `exp` |
| Tampered token signature — 401 | must | |
| Refresh token reuse — both blacklisted (token-reuse detection) | must | If implementing rotation |
| Refresh token expired — 401 | must | |
| Token from another tenant — 403 | must | Multi-tenant only |
| Password reset flow — token single-use, time-limited | must | |
| MFA enabled — login without MFA challenge fails | must | If MFA exists |
| Logout invalidates refresh token | must | |
| Brute-force lockout / rate limit on `/login` | should | |

---

## 6. Background Tasks (BackgroundTasks + Celery)

| Case | Level | Notes |
|------|-------|-------|
| `BackgroundTasks` task runs after response, has access to context | must | |
| Celery task — happy path | must | Use `CELERY_TASK_ALWAYS_EAGER=True` for unit tests |
| Celery task — retry on transient failure | must | Assert retry count |
| Celery task — gives up after `max_retries`, dead-letter | must | |
| Tenant context propagated into worker | must | Multi-tenant only |
| Task is idempotent if it might be retried | must | |

---

## 7. Database Migrations

| Case | Level | Notes |
|------|-------|-------|
| `alembic upgrade head` runs cleanly on empty DB | must | CI test |
| `alembic upgrade head && alembic downgrade -1 && upgrade head` round-trips | must | Catches missing `downgrade()` logic |
| New tenanted table — RLS enabled (lint) | must | Multi-tenant only |
| Backfill data migration is idempotent | must | Safe to re-run |
| Index added concurrently (where supported) | should | Avoids prod table locks |

---

## 8. File Uploads

| Case | Level | Notes |
|------|-------|-------|
| Valid PDF/PNG accepted, stored, key returned | must | |
| Wrong MIME type rejected | must | |
| MIME header lies (real bytes don't match) — rejected | must | Magic-byte sniff |
| Oversize rejected at middleware | must | |
| Path-traversal in filename ignored (server-generated key used) | must | |
| Download requires authorization | must | |
| Presigned URL flow — confirm step verifies upload arrived | should | |

---

## 9. Contract / Schema Tests

| Case | Level | Notes |
|------|-------|-------|
| Generated `openapi.json` doesn't drift from committed snapshot | must | Detect breaking changes in PRs |
| `oasdiff` against `main` — no breaking changes without version bump | should | |
| Spectral lint passes (operationId set, summaries set, examples present) | should | |
| Generated TS client type-checks against current `openapi.json` | should | |

---

## 10. Performance / Smoke (in CI nightly)

| Case | Level | Notes |
|------|-------|-------|
| `/health` < 50 ms | must | Liveness sanity |
| Each list endpoint p95 < 500 ms with 10k rows seeded | should | Catches missing indexes |
| No N+1 queries on hot paths (assert query count) | must | Use SQLAlchemy event listener in test |

---

## Coverage Targets

- `app/services/` — **90%+** (where logic lives)
- `app/repositories/` — **85%+**
- `app/api/` — **80%+** (mostly wiring; integration tests cover this)
- Overall — **80%+** as a CI gate
- Don't chase 100% — diminishing returns + tempts you to test getters

---

## What NOT to Test

- Pydantic's own validation (e.g. that `EmailStr` rejects "not-an-email")
- SQLAlchemy's own behavior (e.g. that `Session.commit` commits)
- FastAPI's own routing
- Trivial getters/setters
- Generated migrations' SQL output (test the *outcome* by upgrading and querying)

If a test would be invalidated by upgrading a dependency, it's testing the dependency, not your code.
