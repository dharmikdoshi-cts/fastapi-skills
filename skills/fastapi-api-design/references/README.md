# References — fastapi-api-design

Long-form material that supports `SKILL.md` but isn't needed every invocation.

## Sections to extract here over time

When the parent `SKILL.md` grows past ~400 lines, move the following into dedicated files in this folder and link from `SKILL.md`:

- `response-envelope.md` — the full `{success, code, message, data, errors}` shape with all variants (success, error, paginated, partial-success).
- `versioning-strategies.md` — URL versioning, header versioning, deprecation/sunset header timeline, per-version routers.
- `pagination-shapes.md` — offset vs cursor envelope (also covered by `fastapi-pagination-filtering`).
- `schema-design-rules.md` — Pydantic conventions: input vs output schemas, naming (`UserCreate`, `UserOut`), `model_config` patterns.
- `dependency-injection-patterns.md` — Annotated DI aliases, scoped dependencies, request-scoped vs app-scoped.

## What stays in `SKILL.md`

Core decision rules, the canonical envelope shape, and 1-2 short examples per concept. If a reader needs more, they jump here.
