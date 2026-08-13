# Pattern model

## Ownership

- `patterns/<group>/<slug>/`: curated library. Every pattern lives inside a group
  folder (a family such as `aggregation-rollups` or `database-to-clickhouse`).
- `patterns/<group>/group.yaml`: the group's card, one per folder (see Groups).
- `workspace-patterns/<slug>/`: the default repository-local workspace root, flat.
- `CLICKHOUSE_PATTERN_WORKSPACE_DIR`: optional writable workspace root, usually a separate private Git checkout. It is used by `just new`, `just clone`, and `just delete`, and is discovered automatically.
- `CLICKHOUSE_PATTERN_WORKSPACES`: additional discovery-only workspace roots, separated by the platform path separator.
- `just new <slug>`: documentation-first workspace scaffold in the configured writable root.
- `just clone <source> <slug>`: derived editable workspace pattern in the configured writable root.

Workspace patterns are always written flat inside their workspace root; only
the curated library uses group folders. To add a curated pattern, put its
folder inside the right group (create a new group folder with a `group.yaml` if
none fits).

## Groups

Each curated group folder carries a `group.yaml`. The group `key` is the folder
name; a pattern belongs to the group folder it lives in.

```yaml
title: Rollups                       # full family title
label: Rollups                       # short filter-chip label (defaults to title)
description: Turn raw rows into pre-aggregated summaries   # one line, card-fit
icon: transform                      # transform | database | kafka-in | kafka-out | clone
order: 1                             # display order across groups
intro: |-
  First paragraph, shown on the group landing.

  Later paragraphs are revealed behind a "More" toggle.
related:                             # optional cross-links to sibling groups
  - group: kafka-to-clickhouse
    note: To stream the raw events into ClickHouse first
```

`category` and `flow` stay on each pattern as plain taxonomy; grouping is the
folder, not those fields.

## Minimal reference manifest

```yaml
title: Postgres orders to ClickHouse
description: Explains the real data movement and the decision it represents.
mode: reference
category: cdc
flow: ingestion
topology: single
tags: [postgres, cdc]
profiles: []
graph: |-
  changes:
    postgres:orders(label=public.orders)
      -[logical WAL]-> connector:cdc
      -[versioned inserts]-> mergetree:orders(label=analytics.orders)
tradeoffs:
  benefits:
    - One concrete benefit.
  drawbacks:
    - One concrete cost.
```

## Compact graph grammar

Each top-level lane ends with `:`. An indented resource chain declares nodes and directed connections.

```text
lane:
  kind:id(label=display label,key=value)
    -[edge label]-> kind:id
    -> {kind:first, kind:second}
```

Resource identity is `kind:id`; reuse the same identity in later lanes. Add `@scope` for a meaningful deployment scope such as `@shards`, `@replicas`, or a semantic role. Use braces for fan-out. Resource properties are compact factual annotations, not prose paragraphs.

Common kinds include `postgres`, `connector`, `peerdb`, `minio`, `topic`, `client`, `kafka-table`, `mv`, `refreshable-mv`, `distributed`, `mergetree`, and `replicated-mergetree`.

## Runnable additions

Runnable patterns declare non-empty `profiles`, a `driver_node`, and real lifecycle files such as `schema_sql`, `load`, and `verify` (its `sql` and `expected` files). `ready_when` entries provide convergence checks. Never add placeholder runtime files to a reference pattern.

### ClickHouse version bounds (`requires`)

When a pattern only works on a range of ClickHouse versions, declare it. Before applying schema, the runner queries `SELECT version()` on `driver_node` and fails fast with a clear message if the running server is out of range.

```yaml
requires:
  clickhouse_min: "26.8"        # a feature absent below this release
  clickhouse_max: "25.3"        # a ceiling, often from a pinned external component
  note: "Why the bound exists (e.g. a connector's bundled driver), so a max isn't read as a ClickHouse limit."
```

Each bound is compared only on the components it names, so `25.3` covers the whole `25.3.x` series and `26.8` means 26.8 or newer. Either bound may be omitted. This is runtime metadata (a version gate plus a UI badge); it is unrelated to `manifest_version`, which versions the file format itself.

### Supersession (`superseded_by`)

When a pattern still runs but a better native option now exists, link to it. This is advisory only (no gate); the pattern page shows a banner pointing at the replacement.

```yaml
superseded_by: kafka-ingest-sharded-partition-affinity   # slug of the replacement
superseded_since: "26.8"                                  # when the replacement became available
```

Use this for workarounds that a later ClickHouse feature makes unnecessary, rather than deleting them: readers on older versions still need them. `superseded_by` must reference an existing pattern slug.

## Quality checklist

- The graph alone explains who initiates each transfer and where data persists.
- Resource labels match actual databases, tables, engines, topics, or services.
- Snapshot and ongoing-change paths are distinct when their mechanics differ.
- A client/query lane exists only when the query surface is part of the decision.
- Benefits and drawbacks describe selection criteria, not generic marketing.
- Live resource inspection is possible only for the currently running pattern.
- `just diagram` renders without overlap severe enough to hide labels or edges.
