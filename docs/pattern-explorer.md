# Pattern Explorer architecture

## Repository layout

`compose/stack.yml` defines all the services used by the examples. Compose
profiles select only the services a pattern needs:

- `single`: one ClickHouse node
- `cluster`: Keeper + 2 replicas of one shard
- `shards`: 2 independent data shards; Keeper coordinates `ON CLUSTER` DDL
- `s3`: MinIO
- `kafka`: single-node Kafka (KRaft)
- `connect`: Kafka Connect worker + official ClickHouse Sink plugin
- `cdc-ch`: ClickHouse pinned at 25.3 for the Altinity lightweight sink; the
  reproduced 26.6 startup failure is documented in the
  [MySQL CDC compatibility note](../patterns/cdc-mysql-clickhouse/README.md#compatibility)
- `mysql` / `postgres`: CDC sources
- `cdc-mysql` / `cdc-postgres`: Altinity lightweight sink
- `peerdb`: self-hosted PeerDB catalog, Temporal, API, and workers

Curated entries live in `patterns/<slug>/`. A reference entry documents a
structured resource flow without runtime files. A runnable entry additionally
declares Compose profiles, SQL/load steps, checks, and expected output.

Company and team extensions live in `workspace-patterns/<slug>/` by default.
Set `CLICKHOUSE_PATTERN_WORKSPACE_DIR` to a separate private repository to make
it the write target for `just new`, `just clone`, and `just delete`; that root is
also discovered automatically. Additional read-only roots can be supplied with
`CLICKHOUSE_PATTERN_WORKSPACES`. The legacy `cloned-patterns/` root remains a
discovery source for migration.

A pattern names profiles; Pattern Explorer orchestration resolves them to
`COMPOSE_PROFILES=… docker compose up --wait`.

The compose file also runs standalone:

```bash
docker compose -f compose/stack.yml --profile cluster --profile kafka up
```

## Foreground exploration flow

The primary user workflow validates first, then keeps the known-good (or
inspectable failed) environment available until the user finishes:

```text
just run <pattern>
  1. record the foreground session as starting
  2. compose up --wait
  3. apply schema and run the load step
  4. poll each ready_when and compare verify.sql with expected.txt
  5. print the SQL console and schema visualizer links
  6. wait for Enter or Ctrl+C
  7. compose down -v and clear the session
```

Patterns may also declare a compact typed resource graph. When present,
`just run` links the browser architecture diagram in the `BROWSE` section. The
graph declares paths rather than visual coordinates:

```yaml
graph: |-
  ingestion:
    topic:events(partitions=4)
      -[group w3]-> kafka-table:events_queue@ch-s1
      -> mv:events_mv@ch-s1
      -> distributed:events_all
      -[cityHash64(id)]-> mergetree:events@shards

  query:
    client -> distributed:events_all -> mergetree:events@shards
```

Use `just diagram <pattern>` to refresh the shared JavaScript Pattern Explorer
catalog and build the browser site without starting infrastructure. The browser
application is the single diagram renderer; it lists every pattern and
deep-links to the requested one, and its **Download SVG** button exports the
rendered diagram. Patterns without a compact `graph` remain browseable but show
that their architecture is pending.

## Static catalog and local control

The browser application is static-first. `just site` builds the complete
catalog into `.runtime/site/` by default, or into a deployment directory with
`just site --output-dir <path>`. It consists only of `index.html`, `app.css`,
`app.js`, and `catalog.js`; it can be opened directly or hosted on any static
web server.

With no `pattern` query parameter, the application opens on the catalog home:
a searchable card browser with pattern-group and topology filters, catalog counts,
and separate workspace context. The landing page uses the full viewport; the
compact left navigation appears only after choosing a pattern. Choosing a card opens the full architecture;
the browser Back button, the ClickHouse brand, and **All patterns** return to
the catalog. Pattern URLs remain directly linkable as
`?pattern=<pattern-slug>`.

`just build-single` produces `.runtime/pattern-explorer.html`, with the CSS,
JavaScript, and catalog embedded into one self-contained file. It follows the
same single-file distribution model as TraceHouse and works directly from
`file://`; use `--output <path>` to choose a different artifact path.

The ownership boundary is deliberate: `explorer/index.html`, `app.css`, and
`app.js` are the browser application and own all rendering and capability
detection. Python only compiles manifests and the graph DSL into `catalog.js`
and implements the optional control APIs. `explorer/scripts/build-static.mjs`
owns static-site copying and single-file HTML packaging; the local server serves
the checked-in browser application directly rather than generating markup.

The page reports its capability mode explicitly:

- **Static catalog**: search, grouping, descriptions, references, diagrams,
  modal zoom, trade-offs, and SVG download work without a backend. The landing
  page stays focused on browsing; after a pattern is opened, a compact note
  explains that it can be run locally or cloned into Workspace patterns.
- **Local control**: when `/api/config` identifies the local Python control
  plane, the same page additionally enables run, validate, stop, logs, live
  links, and ClickHouse resource inspection.

If the control plane disappears, the page falls back to static-catalog mode;
catalog browsing remains available.

While `just explore` is running, the browser checks the live application and
catalog revision. Changes to `explorer/index.html`, `app.css`, `app.js`, or any
compiled pattern manifest reload the page automatically; no `just site`,
`just diagram`, or `just build-single` step is needed during local editing.
Static exports remain fixed snapshots and must be rebuilt when their source
changes.

The foreground command owns cleanup in a `finally` path. It also translates
termination signals into orderly cleanup. If preparation or validation fails
after ClickHouse becomes reachable, the failure is recorded and the command
still waits so the live state can be inspected. Infrastructure failures with no
reachable ClickHouse endpoint clean up immediately.

## Automated test flow

The command first prints the pattern's `title`, detailed `description`,
profiles, driver, files, and validation plan from `pattern.yaml`. It then emits
a labelled line for each phase below, interleaved with output from Compose and
the load script.

```
just test <pattern>
  1. compose up --wait          # healthchecks gate every service
  2. run schema.sql on driver   # DDL (ON CLUSTER for replicated patterns)
  3. run load (.py / .sql)      # INSERT, Kafka produce, source DML, ...
  4. poll each ready_when       # poll until the data lands / replicates
  5. verify.sql == expected.txt # compare output
  6. compose down -v
```

Two kinds of waiting:

| Waiting for | Mechanism |
|---|---|
| Containers healthy | compose healthchecks + `up --wait` |
| Data consistent | `pattern_explorer.orchestration.wait.wait_for` (tenacity poll) |

## Advanced detached session flow

The detached lifecycle remains for agents and scripts that cannot own the
interactive foreground command. It separates preparation from validation:

```text
just start <pattern>
  1. record the session as starting
  2. compose up --wait
  3. apply schema
  4. run load
  5. record the session as ready and leave it running

just validate
  1. poll each ready_when check
  2. compare verify.sql output with expected.txt
  3. leave the session running
```

The remaining commands operate on the recorded session:

| Command | Effect |
|---|---|
| `just status` | Show phase, profiles, driver URL, reachability, and source drift |
| `just status --json` | Return the same information, including the exact `pattern_dir`, for an agent or script |
| `just reload` | Validate the edited manifest, destroy the stack, and start it cleanly |
| `just stop` | Destroy the stack and its volumes, then clear session state |

A foreground Codex inspection session uses two terminals:

```text
terminal 1$ just run kafka-ingest-replicated

terminal 2$ codex
> $clickhouse-pattern-lab Inspect the running pattern. Explain its data flow
  and verify both replica row counts. Do not modify ClickHouse.
```

Exit Codex, then press Enter in terminal 1. The foreground command removes the
environment automatically. The `start`/`validate`/`stop` sequence remains an
advanced alternative for detached operation.

Session state lives in the ignored `.runtime/session.json`. A setup failure is
recorded with phase `failed` and deliberately left running for inspection. Use
`just reload` after fixing the source or `just stop` to clean it up.

The driver node for every current pattern is published at `localhost:8123`.
This stable address is the connection point for a read-only ClickHouse MCP
server. A second shard or replica, when present, is published at
`localhost:8124`.

Recent ClickHouse versions expose a SQL console at
`http://localhost:8123/play` and the schema visualizer at
`http://localhost:8123/schema`. `just run` prints both exact URLs in a `BROWSE`
section before waiting for input. Detached `start`, `reload`, and `status`
commands also print them with a `MANAGE` section. A normal `just test` tears the
stack down, so it does not print links that would immediately become
unavailable.

The PeerDB CDC pattern additionally exposes PeerDB's Postgres-compatible control
endpoint at `localhost:9900`. Its initial snapshot uses the existing `s3`
profile's MinIO bucket before the PeerDB workers begin applying logical WAL
changes to ClickHouse.

## Workspace patterns

Create a documentation-first pattern from scratch:

```bash
just new our-orders-cdc
just diagram our-orders-cdc
```

Derive an existing implementation when its runtime is a useful starting point:

```bash
just clone cdc-postgres-peerdb my-orders-cdc
```

The derived copy is created at:

```text
workspace-patterns/my-orders-cdc/
```

It contains the complete authored pattern and can use the normal commands:

```bash
just show my-orders-cdc
just run my-orders-cdc
# edit workspace-patterns/my-orders-cdc/...
```

`just list` shows workspace patterns separately. They are excluded from
`just test-all` and parametrized pytest so private extensions do not change the
curated library's test suite. Names cannot collide across library or workspace
roots, and creation never overwrites existing files. The live session records
the exact directory, allowing reload and agent inspection to use the edited
source.

Delete a finished experiment with:

```bash
just delete my-orders-cdc
```

Deletion is limited to managed workspace entries. It refuses to delete curated
library patterns, directories without workspace metadata, and the entry
referenced by the running pattern.

## Agent integration

The repository maintains two Agent Skills: `clickhouse-pattern-lab` operates a
live pattern, while `clickhouse-pattern-author` turns real or proposed
architectures into curated or workspace entries. `just agent-setup` links both
into the discovery locations used by Codex (`.agents/skills`) and Claude Code
(`.claude/skills`).

The normal `just setup` recipe installs Pattern Explorer dependencies and then runs this
agent setup for both supported clients. `just agent-setup` is the standalone
form for reruns and targeted setup.

MCP is a shared protocol, but client configuration is not portable. The
repository therefore tracks two small adapters for the same read-only server:

| Client | Project configuration |
|---|---|
| Codex | `.codex/config.toml` |
| Claude Code | `.mcp.json` |

Use `just agent-status` to verify the client executables, skill links, and MCP
adapter contents. Use `just agent-setup codex` or `just agent-setup claude` to
limit setup to one client. The repeatable `--skills-dir <path>` option supports
other Agent Skills-compatible clients; their MCP configuration still requires
a client-specific adapter.

## Source responsibilities

| Location | Role |
|---|---|
| `patterns/` | curated, reusable pattern content |
| `workspace-patterns/` | company, team, and locally derived pattern content |
| `pattern_explorer/catalog/` | manifest discovery and validation; graph DSL to AST |
| `pattern_explorer/orchestration/` | Compose, sessions, loading, convergence, and validation |
| `pattern_explorer/rendering/` | graph DSL to browser-catalog and static-site compilation |
| `pattern_explorer/server/` | local HTTP control plane and live resource inspection |
| `pattern_explorer/cli.py` | terminal interface used by the justfile |
| `explorer/` | browser HTML, CSS, and JavaScript application |
| `integrations/` | Agent Skills and MCP client setup |

## SQL file constraints

`sql.py` splits `.sql` files on `;` and strips `--` comments with a simple rule,
so keep `schema.sql` / `verify.sql` files to:

- one statement per `;`
- no `;` or `--` inside string literals (an S3 endpoint URL is fine, a literal
  containing those characters is not)

This is enough for the current patterns. A ClickHouse-aware splitter can replace
it when a pattern needs literals with those characters.

## Isolation

Pattern Explorer orchestration runs under the Compose project name `chp` (see
`pattern_explorer/orchestration/stack.py`) and the
services no longer set fixed container names, so a run will not collide with other
compose projects by name. Host ports are still fixed (`8123`, `9092`, `3306`, ...)
because orchestration and load scripts connect from the host; if one is already in
use, `just test` reports it as a port conflict rather than a raw trace.

## Adding a pattern

1. `patterns/<slug>/pattern.yaml`: a compact `title`, a structured `graph` that
   drives the Explorer diagram, a detailed `description`, optional `tradeoffs` split into concrete
   `benefits` and `drawbacks`, optional external `references`,
   `category`, `flow`, `topology`, descriptive `tags`, runtime `profiles`,
   `driver_node`, and `ready_when` checks. Use one `schema_sql` file; cluster-wide
   objects belong in `ON CLUSTER` statements and node identity belongs in
   server macros. Label every end-to-end boundary path by direction. Ingestion
   patterns start with `INGESTION: source -> ClickHouse`. Output patterns split
   the causal path into `INPUT: source -> ClickHouse` and
   `OUTPUT: ClickHouse -> destination`. Label secondary paths as `QUERY`,
   `QUERY + DEDUP`, or `TEST ONLY` rather than presenting unexplained arrows.
   Use the same component names everywhere: `Kafka`, `Kafka Connect`,
   `ClickHouse`, `Kafka engine`, `MV`, `Distributed`, and the concrete local
   table engine. Additional lines may add object names, shards, consumer groups,
   or verification paths. Pair every object name with its role, for example
   `Kafka engine table events_in` or `MergeTree events`. The description should
   explain tradeoffs and the behavior the pattern proves. Both are shown by
   `just describe` and before a run.
2. `schema.sql`, a `load.{sql,py}`, `verify.sql`, `expected.txt`, `README.md`.
3. Generate the reference instead of hand-writing it:

```bash
just test <slug> --update      # writes verify.sql output to expected.txt
```

Patterns are auto-discovered by `just list`, `just test-all`, and pytest.
