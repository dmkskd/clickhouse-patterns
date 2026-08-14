---
name: clickhouse-pattern-author
description: Create, document, extend, or repair ClickHouse library and workspace patterns in this repository. Use when turning a real or proposed data architecture into pattern.yaml and its compact graph DSL, deriving a company/team pattern, adding trade-offs and references, or optionally making that pattern runnable and validated.
---

# ClickHouse Pattern Author

Turn an architecture into a reusable catalog entry whose structured resource graph drives the Explorer diagram. Runtime automation is optional; never invent infrastructure merely to make documentation runnable.

Before changing a pattern, read [references/pattern-model.md](references/pattern-model.md) completely.

## Choose the authoring path

- For a new company or team architecture, run `just new <slug>`. It creates a documentation-first entry under `workspace-patterns/` by default.
- To adapt an existing implementation, run `just clone <source> <slug>`. Preserve the derived runtime until the requested changes require otherwise.
- Edit curated `patterns/` only when the user explicitly wants the shared library changed.

For private or team-owned patterns, set `CLICKHOUSE_PATTERN_WORKSPACE_DIR` to a
separate Git checkout before creating or cloning. `just new`, `just clone`, and
`just delete` then use that checkout, which is also discovered automatically by
the Explorer and CLI. Do not put private patterns in the public catalog merely
to make them discoverable.

Use lowercase hyphenated slugs. The `graph` is the single canonical representation of a pattern's architecture.

## Document the architecture

1. Inspect the relevant source files and, for a live system, use read-only metadata or query evidence. Preserve an active Pattern Lab session unless the user asks to replace it.
2. Model real resources and ownership boundaries: source systems, connectors, staging, ClickHouse tables/views, clients, and operational state only when it materially explains the flow.
3. Separate semantically distinct lanes such as snapshot, changes, ingestion, query, replication, or transformation.
4. Label connections with the mechanism that moves data, not a vague verb. Examples: `logical WAL · pgoutput`, `INSERT target FROM s3()`, `materialized view insert`.
5. Write a concise description that answers what happens and why the pattern exists. Add concrete `tradeoffs.benefits` and `tradeoffs.drawbacks`.
6. Link primary upstream documentation or a precise issue when it supports a compatibility or behavior claim.
7. Set the pattern's `status` so colleagues understand its readiness: use `wip` while it is actively being written or changed, `under-review` for a complete candidate awaiting sign-off, and `stable` only once it is a maintained recommended starting point. This is independent of `mode` (`runnable` or `reference`) and `experimental`.

Do not expose credentials, copy production data, or claim runtime behavior that was not verified. Never query a ClickHouse Kafka-engine table directly because that consumes messages.

## Add runtime only when useful

A reference pattern uses `mode: reference`, needs no profiles, and can render immediately. A runnable pattern uses `mode: runnable` (the default) and must declare real profiles, driver node, setup/load steps, convergence checks, and deterministic verification.

Prefer a small representative dataset and current-state assertions. Verify declared table names, engines, ownership, and routing against the actual DDL or live metadata.

## Validate and hand off

Run:

```text
just show <slug>
just diagram <slug>
uv run pytest -q tests/test_architecture.py tests/test_clones.py tests/test_cli.py
```

For a runnable pattern, also run `just test <slug>` when doing so will not replace a user's live session. Report whether the architecture was verified from source, from a live system, or is intentionally conceptual.
