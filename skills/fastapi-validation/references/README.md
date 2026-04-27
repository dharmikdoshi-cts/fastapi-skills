# References — fastapi-validation

Long-form material that supports `SKILL.md` but isn't needed every invocation.

## Purpose

When the parent `SKILL.md` grows past ~400 lines or a section bloats with edge-case detail, **extract here** as a focused `.md` file and link from `SKILL.md`.

This keeps `SKILL.md` lean (fast to load, easy to scan) while preserving depth for when readers need it.

## Suggested file naming

```
<topic>.md           e.g. retry-strategies.md, hash-chain-spec.md
<pattern>-deep-dive.md
<edge-case>-cheatsheet.md
```

## What stays in `SKILL.md`

- Core decision rules
- One canonical example per concept
- Anti-patterns table
- Verification checklist

Anything else — extended examples, framework-version comparisons, regulatory notes, migration playbooks — belongs here.
