---
name: clickhouse-pattern-lab
description: Operate the live ClickHouse pattern lab in this repository. Use when asked to start, inspect, explain, troubleshoot, modify, reload, or validate a runnable pattern; when a user mentions the running pattern or pattern session; or when ClickHouse MCP evidence must be compared with pattern.yaml, README, schema, load, verification, and expected-output files.
---

# ClickHouse Pattern Lab

This skill requires `uv`, Docker, `just`, and a read-only ClickHouse MCP server
named `clickhouse-patterns`.

Connect three sources of truth:

- Use `just status --json` for the active session.
- Use the `pattern_dir` returned by `just status --json` for intended behavior.
  It points to `patterns/<slug>/` for library patterns and
  a configured workspace root for company, team, and locally derived patterns.
  The writable root can be a separate private Git checkout selected with
  `CLICKHOUSE_PATTERN_WORKSPACE_DIR`.
  The old `cloned-patterns/` root remains readable for migration compatibility.
- Use the read-only ClickHouse MCP for observed runtime state.

Do not treat the MCP connection name as pattern metadata. Discover the active
slug before interpreting the database.

## Choose The Workflow

- For a static explanation, read the requested pattern files without starting it.
- For user-driven exploration, have the user run `just run <slug>` in a terminal;
  it validates, exposes the live environment while it waits, and cleans up on
  Enter or Ctrl+C.
- For live inspection or troubleshooting, use an active foreground run. When
  an agent must create a session without an interactive terminal, use the
  advanced detached `just start <slug>` workflow.
- For validation with no active session, use `just test <slug>`.
- For validation with an active session, use `just validate`.
- For iteration, edit source, run `just reload`, then run `just validate`.

## Discover The Session

Run:

```bash
just status --json
```

Sessions created before clone support may not contain `pattern_dir`. For that
legacy case only, fall back to `patterns/<slug>/`; new sessions always report
the exact directory.

Use `slug`, `phase`, `driver_node`, `driver_url`, `reachable`, and
`source_changed` from the result.

- If no session is active and the user requested interactive exploration, tell
  them to run `just run <slug>` in a terminal. Do not launch it through a
  non-interactive agent command because it intentionally waits for input.
- If no session is active and the user explicitly asked the agent to perform
  detached live work, run `just start <slug>`.
- If no session is active and no pattern can be inferred, run `just list` and
  ask for the intended pattern only when selection is genuinely ambiguous.
- If `phase` is `failed`, preserve the environment for diagnosis. Do not reload
  or stop it before collecting evidence. If the record itself cannot be acted on,
  such as a pattern directory that no longer exists, see Recover A Broken
  Environment.
- If `source_changed` is true, state that the live environment may represent the
  previous source. Do not reload during inspection unless the user requests it.

Only one running pattern is supported. Do not start another while a foreground
run or detached session is active.

## Read The Pattern Intent

Open `<pattern_dir>/pattern.yaml` first, using the exact directory reported by
session status. Follow its file fields rather than assuming standard filenames.
Manifest keys are grouped: catalog fields under `metadata:`, runtime fields
under `spec:` (with the lifecycle under `spec.steps:`). Read the files that exist:

1. `metadata.category`, `metadata.flow`, `metadata.topology`, and `metadata.tags` for the declared taxonomy.
2. `metadata.graph` for the declared data paths and topology (the resource-flow DSL).
3. `metadata.references` for relevant upstream documentation and issue context.
4. `README.md` for the technique and known constraints.
5. `spec.steps.schema` for the concrete topology and data flow.
6. `spec.steps.load` for the input data and operational sequence.
7. `verify.sql` and `verify.expected` for deterministic output.
8. `spec.steps.ready_when` for convergence checks, nodes, values, and timeouts.

Use the `graph` as the initial topology claim, then verify it against the SQL,
load code, and runtime objects. Each top-level lane (a name ending in `:`, such
as `ingestion:`, `snapshot:`, `changes:`, `transformation:`, or `query:`) is a
separate data path; the indented `kind:id -[edge]-> kind:id` chains name the
objects and how data moves between them.
Use the manifest vocabulary when reporting
components: Kafka, Kafka Connect, ClickHouse, Kafka engine, MV, Distributed,
and the concrete local table engine. Summarize the declared sources,
transforms, destinations, topology, and validation contract before drawing
conclusions from runtime state.

## Inspect Through MCP

Prefer the MCP registered as `clickhouse-patterns`. Tool names can be namespaced
by the client; use the equivalents of `list_databases`, `list_tables`, and
`run_query`. If an Altinity MCP exposes `execute_query`, treat that as the
read-only query equivalent.

Begin with metadata and cheap checks:

```sql
SELECT version(), hostName();

SELECT database, name, engine, create_table_query
FROM system.tables
WHERE database NOT IN ('system', 'information_schema', 'INFORMATION_SCHEMA')
ORDER BY database, name;
```

Then inspect only objects relevant to the manifest and schema. Verify engines,
columns, materialized-view targets, dependencies, row counts, and the values
asserted by `ready_when` or `verify.sql`.

For replicated or sharded patterns, inspect topology through `system.clusters`.
When the driver can address the declared cluster, compare replicas from the
single MCP connection with a query shaped like:

```sql
SELECT hostName(), count()
FROM clusterAllReplicas('<cluster>', <database>.<table>)
GROUP BY hostName()
ORDER BY hostName();
```

Use `just validate` as the authority when manifest checks target host ports or
services the MCP cannot reach directly.

### Kafka Safety

Never select from a table whose engine is `Kafka` during inspection. Reading it
can consume messages and change the pattern being investigated. Inspect its
definition through `system.tables` and query its durable destination instead.

## Compare Intent With Runtime

Keep declarations and observations distinct:

- Attribute manifest, README, and SQL claims to pattern source.
- Attribute database engines, schemas, counts, and dependencies to MCP queries.
- Report missing objects, unexpected engines, count mismatches, and source drift.
- Include the small queries or results that support important conclusions.
- Do not claim a pattern is valid solely because its objects exist.

Run `just validate` when validation is requested. It performs the manifest's
per-node convergence checks and compares `verify.sql` with `verify.expected` while
leaving the session running.

## Iterate Reproducibly

Make changes in repository files, never through MCP:

1. Edit the manifest, SQL, load code, expected output, or documentation.
2. Run `just status` and confirm that source drift is detected.
3. Run `just reload` to rebuild cleanly from the edited source.
4. Run `just validate`.
5. Inspect the rebuilt runtime through MCP when evidence is needed.

## Recover A Broken Environment

`just reset` is the recovery path when the session record and the running
containers disagree: a run interrupted partway, containers left behind by a
failed start, an unreadable state file, or a session whose pattern directory was
renamed or deleted. It removes the Compose project across every profile and
clears the session state, so it does not depend on the manifest still loading.

Use it only after collecting the evidence a failed session holds, because it
destroys that environment. Confirm with the user before running it, and check
`docker ps` first: the Compose project is shared, so a reset also removes
containers belonging to a `just run` the user owns in another terminal.

`just stop` remains the ordinary way to end a session.

`reload` destroys session volumes. Use it only after an intentional source edit
or an explicit request. A foreground `just run` owns its cleanup; do not call
`just stop` while it is waiting. For detached sessions, do not call `just stop`
automatically after live inspection unless cleanup was requested.

## Safety Contract

- Keep MCP queries read-only: `SELECT`, `SHOW`, `DESCRIBE`, and `EXPLAIN`.
- Never use MCP for `CREATE`, `ALTER`, `INSERT`, `DELETE`, `DROP`, `TRUNCATE`,
  `OPTIMIZE`, or other mutations.
- Never query a Kafka-engine table directly.
- Prefer measured pattern behavior over generic database advice.
- Use external ClickHouse or Altinity skills for domain reasoning when
  available, but verify their recommendations against this pattern and runtime.

## Report

Return a concise result with:

1. Active pattern and session health.
2. Intended data flow and validation contract.
3. Observed runtime objects and measurements.
4. Differences or risks.
5. Validation result and whether the session remains running.
