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

Each curated group folder has a `group.yaml`. The group `key` is the folder
name; a pattern belongs to the group folder it lives in.

```yaml
title: Rollups                       # full family title
label: Rollups                       # short filter-chip label (defaults to title)
description: Aggregate raw data into summary views   # one line, card-fit
icon: rollup                         # database | s3 | kafka-in | kafka-out | clock | rollup | clone | lake
order: 1                             # display order across groups
intro: |-
  First paragraph, shown on the group page.

  Later paragraphs are revealed behind a "More" toggle.
related:                             # optional cross-links to sibling groups
  - group: kafka-to-clickhouse
    note: To stream the raw events into ClickHouse first
links:                               # optional curated external reading
  - label: "Performance impact of materialized views in ClickHouse (Altinity)"
    url: https://altinity.com/blog/performance-impact-of-materialized-views-in-clickhouse
    note: One line saying why this is worth reading (hover tooltip)
```

Grouping is the folder; patterns have no separate category field.

Pattern readiness is declared in `pattern.yaml`, independently of whether it is
runnable or reference-only:

```yaml
metadata:
  status: wip                         # wip | under-review | stable
```

Use `wip` while a pattern is actively being written or changed, `under-review`
for a complete candidate awaiting sign-off, and `stable` only for a maintained
recommended starting point. Status is shown on the individual pattern, not its
group. It is independent of `mode` and `experimental`.

## Manifest layout (manifest_version: 2)

A `pattern.yaml` has two sections, in the Kubernetes/Backstage style:
`metadata:` holds everything the catalog shows (title, description, graph,
taxonomy, links, tradeoffs); `spec:` holds everything the runner executes
(profiles, driver node, service customization, and the ordered lifecycle under
`steps:`). `manifest_version: 2` sits at the top level. Older flat files are
rejected; rewrite them with `just migrate` (or `python -m pattern_explorer migrate`).

## Minimal reference manifest

```yaml
manifest_version: 2
metadata:
  title: Postgres orders to ClickHouse
  description: Explains the real data movement and the decision it represents.
  status: wip
  topology: single
  tags: [postgres, cdc]
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
spec:
  mode: reference
  profiles: []
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

Runnable patterns declare non-empty `spec.profiles`, a `spec.driver_node`, and the ordered lifecycle under `spec.steps:`: `schema` (DDL applied to the driver node), `load` (a `.sql` or `.py` seed/demo step), `ready_when` (convergence checks), and `verify` (its `sql` and `expected` files). Never add placeholder runtime files to a reference pattern.

```yaml
spec:
  profiles: [single, postgres]
  driver_node: ch
  steps:
    schema: schema.sql
    load: load.py
    ready_when:
      - query: SELECT count() FROM demo.events
        value: 3
    verify:
      sql: verify.sql
      expected: expected.txt
```

In `expected.txt`, lines starting with `#` are annotations and are ignored by
the comparison. Add a tab-separated `#` header naming the columns (matching the
`verify.sql` aliases) so readers can tell what each value is; the explorer
renders it as a header row, and `just test <slug> --update` preserves it.

### Per-service customization (`spec.services`)

`spec.services:` customizes the compose services a pattern runs against, keyed
by service. `clickhouse.config` mounts additive XML fragments,
`<database>.init` mounts SQL init scripts, and `<service>.config` mounts native
configuration files for non-ClickHouse services.

#### ClickHouse configuration

Use `spec.services.clickhouse.config` for additive XML fragments that a runnable
pattern needs on a particular ClickHouse service. The runner mounts each
fragment only for that pattern, under `config.d` (the default) or `users.d`; it
never replaces the shared `config.xml`. Sources are relative to the pattern
directory and must be `.xml` files. The fragment is merged by ClickHouse at
server startup, so reload the pattern after changing it.

```yaml
spec:
  services:
    clickhouse:
      config:
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

#### Database init scripts (`postgres` / `mysql`)

Use `spec.services.<database>.init` for SQL the source database should run when
its container initializes — the tables and seed rows the pattern assumes, kept
inside the pattern directory instead of the stack's shared seed. The runner
mounts each script into the service's `/docker-entrypoint-initdb.d`, where the
image entrypoint runs it after the shared `init.sql` seed (the mount name has a
`zz-pattern-` prefix, and the directory executes alphabetically). Init runs on a
fresh container, which every session gets: the stack always comes down with
`down -v` between sessions. Scripts must be `.sql` files relative to the pattern
directory; `init` accepts one file or a list.

```yaml
spec:
  services:
    postgres:
      init: seed.sql            # or [schema.sql, seed.sql]
```

Use this for the static starting state a pattern reads from. Keep the mutations
the pattern demonstrates (the INSERT/UPDATE/DELETE a demo performs) in
`steps.load`, not in init. The shared `compose/cdc/postgres-init.sql` and
`mysql-init.sql` seeds remain the base for patterns that use the common
`orders` tables; a pattern's own init is additive to them.

#### Native connector configuration

Use `spec.services.<service>.config` for native configuration files consumed by
other Compose services. Each entry declares a pattern-relative `file` and an
absolute container `target`. Mounts are read-only; a matching target replaces
the shared stack's mount for that pattern.

```yaml
spec:
  services:
    walshadow:
      config:
        - file: config/latency.toml
          target: /etc/walshadow/ch-config.d/10-pattern.toml
```

Use `config/` for editable configuration read by a host-side loader as well,
such as Kafka Connect JSON payloads or PeerDB mirror SQL. The Explorer displays
native configuration files in `config/` in its Configuration panel. The loader
must actually read these files; discovery only displays them. Run `just reload`
and `just validate` after editing them. Reload rebuilds the demo and clears data.

### Experiments (`spec.experiments`)

An experiment is a script in the pattern folder that runs on demand against the
active session: a workload, a setting change, a fault. It never runs as part of
`just run`, `just test` or `just validate`. Readers start it from the
Explorer's **Experiments** panel or with `just experiment <name>
[parameter=value ...]`; each completed run adds one row to the panel's results
table. The four database CDC patterns have a `replication-latency` experiment
to copy from.

```yaml
spec:
  experiments:
    - name: replication-latency
      title: Replication latency
      description: Inserts orders into Postgres at a fixed rate and measures the time from the Postgres write to the ClickHouse insert.
      script: experiments/replication_latency.py
      parameters:
        - name: flush_timeout_ms              # config parameter: written to the file, then the session reloads
          label: walshadow flush timeout (ms)
          short: flush ms
          group: walshadow
          default: 1000
          min: 1
          config: {file: config/latency.toml, key: flush_timeout_ms}
        - name: rate                          # script parameter: passed as --rate 50
          label: Rows per second
          short: requested/s
          group: Postgres
          default: 50
          min: 1
      results:
        - name: p50_ms
          label: p50
          group: End to end (ms)
          description: Median time from the Postgres write to the ClickHouse insert, per row.
      groups: [Postgres, walshadow, ClickHouse, End to end (ms)]
      timeline_total: Average row latency (write to insert)
```

Parameters:

- `name` (snake case), `label` (the form field), `short` (the table column) and
  `group` (the table header group).
- `default` is a number or text. A number accepts any value at or above `min`;
  set `min` explicitly, because there is no implicit lower bound. Text needs
  `choices`, rendered as a dropdown, so a free-form string never reaches a
  config file or a command line. `choices` also works for numbers.
- With `config: {file, key}`, the runner sets the first `key` line in a copy of
  that pattern file under `.runtime/experiment-config/<slug>/`; the pattern file
  is never edited. It handles `key = value` (TOML, SQL options), `key: value`
  (YAML) and `"key": "value"` (JSON). When the copies change, the session
  reloads to read them, which clears its data. The session keeps the copies
  after the run, so further runs at the same values need no reload; the
  Explorer shows the values in use with a **Restore committed config** button,
  and any `just reload`, `just stop` or new start goes back to the pattern's
  files.
- The pattern must read the file at session start. A
  `spec.services.<service>.config` mount picks up the copy automatically. A
  loader that reads `config/` itself must open it through
  `config_file(Path(__file__).parent, "config/<file>")` from
  `pattern_explorer.orchestration.config_overlay`, or it ignores the
  experiment's value.
- Without `config`, the value is passed to the script as
  `--<name-with-dashes> <value>`.

Results, groups and timeline:

- `results` declares the label, `group` and one-line `description` of each key
  the script reports. The panel shows the description on hover and in the
  legend. Undeclared keys still appear, after the declared ones.
- `groups` orders the header groups left to right. Name groups after pipeline
  stages (source database, replication tool, ClickHouse, end to end) so a column
  such as INSERTs reads as ClickHouse's.
- `timeline_total` labels the sum of the stages in the timeline tooltip.

The script contract:

- It runs with the repository root on `PYTHONPATH`, from the pattern
  directory. Every stdout line appears in the Explorer log.
- The last line is `RESULT {json}`: result name to number or text. Text results,
  such as a verdict or a mode, display and sort as text. An optional `stages`
  list of `{label, ms, extra}` draws the per-run timeline bar; segments are
  drawn in list order, and `extra: true` marks a segment that is shown but not
  added to `timeline_total`, such as a per-statement average next to per-row
  stages.
- A non-zero exit fails the run, and failed runs are not saved. **Stop** in the
  Explorer sends the script SIGTERM; it cannot interrupt a config reload.
- Runs are saved to `.runtime/experiments/<slug>.jsonl`, outside the pattern's
  volumes, so they survive reloads; **Reset** in the panel deletes them.

`pattern_explorer/orchestration/probe.py` has the shared pieces for CDC
workloads: `workload_args()` (`--rate`, `--rows-per-txn`, `--duration`),
`postgres_workload()` and `paced()` for writing a fresh id range at a fixed rate,
`latency_summary()` and `stage_summary()` for the ClickHouse side, and
`insert_stage()` and `result_line()` for the output.

Rules for measurements:

- Build a stage boundary only from a column whose meaning is confirmed in the
  tool's source at the pinned version, and cite the file in a comment next to the
  expression. When a tool records no time for a step, merge the steps into one
  stage and say so in its label.
- Report stages as averages, not medians, so they add up to the average total.
- Take the run's start time from ClickHouse (`now64()`), not the host, when
  filtering `system.part_log` or `system.query_log`.
- Write a fresh id range above the rows `load.py` writes, so runs do not mix.
- Report what the workload achieved next to what it requested
  (`achieved_rate`), so a source that cannot keep up is visible.

### ClickHouse version bounds (`requires`)

When a pattern only works on a range of ClickHouse versions, declare it. Before applying schema, the runner queries `SELECT version()` on `driver_node` and fails fast with a clear message if the running server is out of range.

```yaml
spec:
  requires:
    clickhouse_min: "26.8"        # a feature absent below this release
    clickhouse_max: "25.3"        # a ceiling, often from a pinned external component
    note: "Why the bound exists (e.g. a connector's bundled driver), so a max isn't read as a ClickHouse limit."
```

Each bound is compared only on the components it names, so `25.3` covers the whole `25.3.x` series and `26.8` means 26.8 or newer. Either bound may be omitted. This is runtime metadata (a version gate plus a UI badge); it is unrelated to `manifest_version`, which versions the file format itself.

### Supersession (`superseded_by`)

When a pattern still runs but a better native option now exists, link to it. This is advisory only (no gate); the pattern page shows a banner pointing at the replacement.

```yaml
metadata:
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
metadata:
  related_patterns:
    - slug: ttl-policy-change-rollout
      note: Read before changing this table's TTL on existing data.
```

**Group cross-reference — `related`** in `group.yaml`, linking group to group.
Use for a neighbouring family, not for an individual pattern.

**Group external reading — `links`** in `group.yaml`. Use for curated external
articles that apply across the whole family; the `note` says why the link is
worth reading. They render as a "Further reading" list on the group page.
An article about one pattern's specific mechanism belongs in that pattern's
`references` instead.

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
