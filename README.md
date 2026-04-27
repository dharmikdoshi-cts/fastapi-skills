# fastapi-skills

A Claude Code plugin: 18 production-grade FastAPI engineering skills covering project structure, database, security, testing, observability, multi-tenancy, audit trail, and more.

Python 3.12+ · FastAPI · async SQLAlchemy 2.x · Pydantic v2 · Alembic · pytest

---

## Skills

### Project structure
- **fastapi-simple** — flat layout for small/medium APIs (< 50 endpoints, MVPs)
- **fastapi-modular** — domain-based modular layout for large/enterprise APIs

### Data layer
- **fastapi-database** — async engine, session, `BaseAsyncRepository`, Alembic migrations (one-per-table, `ddmmyyyy_hhmmss_<slug>` naming)
- **fastapi-multi-tenancy** — shared schema + Postgres RLS, schema-per-tenant, db-per-tenant
- **fastapi-audit-trail** — change tracking, soft-delete, append-only ledger with hash chain

### API design
- **fastapi-api-design** — FE-friendly response envelope, versioning, schemas, pagination, deprecation
- **fastapi-validation** — Pydantic v2 validators, reusable typed primitives, sanitization
- **fastapi-pagination-filtering** — offset + cursor pagination, allow-listed sort, filter DSL, full-text search
- **fastapi-file-uploads** — streamed uploads, magic-byte validation, S3 / presigned URLs, virus scan
- **fastapi-openapi-docs** — operation IDs for codegen, examples, security schemes, doc protection

### Cross-cutting
- **fastapi-security** — JWT (access + refresh), bcrypt, RBAC, CORS, rate limiting, security headers
- **fastapi-config-secrets** — `pydantic-settings` v2, layered `.env`, secret managers, redaction
- **fastapi-exception** — global exception handlers, FE-friendly error envelope
- **fastapi-logging** — structured JSON logs with request ID + trace correlation
- **fastapi-observability** — Prometheus metrics, OpenTelemetry tracing, Sentry, healthchecks, SLOs
- **fastapi-background-task** — `BackgroundTasks` vs Celery, retries, scheduled jobs
- **fastapi-typing** — strict mypy/pyright config, `Annotated` DI, `Protocol`, `NewType`

### Testing
- **fastapi-testing** — async pytest, `FakeRepository`, contract tests, per-layer test-case catalog

---

## Install

```bash
# In Claude Code:
/plugin marketplace add /path/to/fastapi-skills
/plugin install fastapi-skills
```

Or add to `~/.claude/settings.json`:

```json
{
  "plugins": {
    "fastapi-skills": "/path/to/fastapi-skills"
  }
}
```

---

## Usage

Once installed, the skills are auto-discovered. Invoke a skill in Claude Code with:

```
/fastapi-database
/fastapi-security
/fastapi-testing
```

…or describe what you're doing — Claude will pick the right skill from the descriptions.

---

## Skill anatomy

Each skill follows the same layout:

```
fastapi-<topic>/
├── SKILL.md              ← the skill (loaded into context)
├── examples/             ← runnable .py reference files
├── tests/                ← pytest demonstrations
└── references/           ← long-form material kept out of SKILL.md
```

`SKILL.md` is the lean entry point — decision rules, one canonical example per concept, anti-patterns, verification checklist. Deeper material lives in `references/`. Copy-paste-ready code lives in `examples/`.

---

## Conventions used across all skills

- Python 3.12+, modern type syntax (`X | None`, `list[T]`, `dict[K, V]`)
- `Annotated[T, Depends(...)]` for dependency injection
- `Protocol` for repository / service contracts (no ABCs, no mocking libraries)
- FE-friendly response envelope: `{success, code, message, data, errors}` for every response
- Alembic: one migration per table, filename pattern `DDMMYYYY_HHMMSS_<slug>.py` (UTC)
- Tests use `FakeRepository` for unit, real Postgres (rolling-back transaction) for integration

---

## Versioning

CalVer-friendly — bump `version` in `.claude-plugin/plugin.json` per substantive change.

---

## License

Internal — Comprint.
