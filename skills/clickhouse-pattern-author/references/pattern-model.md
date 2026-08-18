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

Pattern readiness is declared in `pattern.yaml`, independently of whether it is
runnable or reference-only:

```yaml
status: wip                         # wip | under-review | stable
```

Use `wip` while a pattern is actively being written or changed, `under-review`
for a complete candidate awaiting sign-off, and `stable` only for a maintained
recommended starting point. Status is shown on the individual pattern, not its
group. It is independent of `mode` and `experimental`.

## Minimal reference manifest

```yaml
title: Postgres orders to ClickHouse
description: Explains the real data movement and the decision it represents.
mode: reference
status: wip
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
  limitations:
    - One concrete limitation.
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

### Per-pattern ClickHouse configuration

Use `clickhouse_config` for additive XML fragments that a runnable pattern needs
on a particular ClickHouse service. The runner mounts each fragment only for
that pattern, under `config.d` (the default) or `users.d`; it never replaces the
shared `config.xml`. Sources are relative to the pattern directory and must be
`.xml` files. The fragment is merged by ClickHouse at server startup, so reload
the pattern after changing it.

```yaml
clickhouse_config:
  - node: ch
    file: config/tiered-storage.xml
    directory: config.d                 # config.d | users.d
    name: tiered-storage.xml            # optional; source basename by default
    depends_on: [minio-init]            # optional Compose services that must be healthy first
```

Use this for server concerns such as a storage policy, named collection, system
log, or user profile needed by one example. Keep table-specific settings in DDL
(`SETTINGS storage_policy = ...`) and do not put credentials in a committed
fragment; use development-only values or an environment-backed configuration.

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

## Linking patterns

Four mechanisms exist and they are not interchangeable. Pick by where the reader
is when the link should appear.

**Inline in prose — `[[slug|label]]`** in a pattern `description`. Use when the
sentence itself names another pattern and the reader should be able to follow it
mid-thought. The label is the link text, so write the sentence first and let the
link fall where the name already is.

```yaml
description: |-
  This is the replicated companion to [[ttl-move-to-s3|Hot/cold placement: TTL
  move to an S3 volume]].
```

External documentation can be linked inline the same way: `[label](url)` in a
description renders as an external link in the Explorer and as the plain label
in the CLI. Use it when a named term or bullet has its own primary doc, so the
link sits where the reader meets the term; keep `references` for links that are
not tied to one phrase.

**Standing pointer — `related_patterns`** on a pattern. Use for a pattern the
reader should know about even though the prose does not name it, such as guidance
to read before changing this table. It renders as "Related guidance" buttons
below the description, and the `note` says why the link is there.

```yaml
related_patterns:
  - slug: ttl-policy-change-rollout
    note: Read before changing this table's TTL on existing data.
```

**Group advisory — `advisories[].link_pattern`** in `group.yaml`. Use when a
caution applies across the whole family and one pattern explains it. It appears
on the group landing page, before the reader has chosen a pattern.

**Group cross-reference — `related`** in `group.yaml`, linking group to group.
Use for a neighbouring family, not for an individual pattern.

Do not point at the same slug both inline and in `related_patterns`; the inline
link already puts it in the reader's path.

## Quality checklist

- The graph alone explains who initiates each transfer and where data persists.
- Resource labels match actual databases, tables, engines, topics, or services.
- Snapshot and ongoing-change paths are distinct when their mechanics differ.
- A client/query lane exists only when the query surface is part of the decision.
- Benefits and limitations describe selection criteria, not generic marketing.
- Live resource inspection is possible only for the currently running pattern.
- `just diagram` renders without overlap severe enough to hide labels or edges.
