# ClickHouse Pattern Explorer

## Overview

ClickHouse is a fast and flexible analytics engine. It offers several table
engine families and multiple ways to ingest, process, replicate, and distribute
data.

For many ClickHouse systems, query speed is not the main design challenge. The
harder part is choosing and combining the right building blocks for ingestion,
data modelling, delivery guarantees, replay and backfills, and cluster topology.

This repository is a catalog of runnable patterns for those choices, covering
ingestion, output, CDC, replication, and sharding. Each pattern starts the
services it needs, loads test data, and checks that it worked as expected.

## Explore locally

```bash
just setup      # install the Pattern Explorer and agent integrations
just explore    # open the catalog at http://localhost:8765
```

`just explore` serves the whole catalog with a local control plane. Patterns can
be compared through their resource diagrams and trade-offs, started with the
services they need, inspected while running through the SQL console and live
table metadata, and torn down again from the same page.

## Other ways to run it

The catalog also works without a backend. `just site` writes a deployable copy
to `.runtime/site/`, whose HTML, CSS, JavaScript, and catalog data need no Python
service, and that page labels itself **Static catalog**. Running `just explore`
serves the same application with the local control plane, where the label
changes to **Local control** and the lifecycle and live-inspection features
become available. For sharing, offline use, or opening directly from `file://`,
`just build-single` inlines the whole application and catalog into
`.runtime/pattern-explorer.html`.

Every pattern can also be driven from the command line:

```bash
just list                          # list the available patterns
just describe                      # explain what each pattern demonstrates
just run kafka-ingest-replicated   # validate a pattern, then clean up on Enter
just test kafka-ingest-replicated  # non-interactive run that tears down at the end
just reset                         # recovery: remove every container and clear the session
```

Use `just reset` when the lab and the recorded session disagree: a run that was
interrupted, containers left behind, or a session pointing at a pattern that has
since been renamed. It removes the Compose project across every profile and
deletes the session state, so the next `just run` starts from a clean state.
`just stop` remains the ordinary way to end a session.

For example, `kafka-ingest-replicated` sends 20,000 Kafka messages into a
two-replica ClickHouse table and checks that every message reached both replicas:

```text
$ just run kafka-ingest-replicated
...
  LOAD    load.py -> ch-01
produced 20000 messages to 'events' on localhost:9092
  CHECK   ch-01: ... == (20000,20000,0,19999)
  CHECK   ch-02: ... == (20000,20000,0,19999)
  VERIFY  matched (1 row(s))
  RESULT
          20000  20000  0  19999  6667  6666  6667
PASS  kafka-ingest-replicated

  BROWSE
    SQL console        http://localhost:8123/play
    schema visualizer  http://localhost:8123/schema

  Press Enter to finish and remove containers and volumes (Ctrl+C also finishes).
```

While `just run` waits, the pattern stays available for inspection through the
ClickHouse SQL console, the schema visualizer, another terminal, MCP, or an Agent
Skill, and the containers and volumes are removed on Enter or Ctrl+C.

## Create your own patterns

Patterns are designed to be explored, adapted, and extended. Create a new
documentation-first workspace pattern, or clone a runnable example when its
flow and Docker infrastructure are a useful starting point:

```bash
just new our-orders-cdc
just clone cdc-postgres-peerdb my-orders-cdc
# by default, both create entries under workspace-patterns/
```

To keep patterns committed in a separate private repository, clone that
repository alongside this one and make it the writable workspace root:

```bash
git clone git@github.com:your-org/clickhouse-pattern-workspaces.git ../pattern-workspaces
export CLICKHOUSE_PATTERN_WORKSPACE_DIR="$PWD/../pattern-workspaces"
just clone cdc-postgres-peerdb my-orders-cdc
just list                         # confirms the workspace pattern is discovered
just explore                      # shows it in Pattern Explorer's Workspace group
```

`CLICKHOUSE_PATTERN_WORKSPACE_DIR` is used for `just new`, `just clone`, and
`just delete`, and is discovered automatically by every command launched with
that environment, including `just list`, `just run`, and `just explore`. Static
catalogs (`just site` and `just build-single`) include the configured workspace
patterns when they are built. Keep the setting in a local shell or `direnv`
configuration; the public catalog checkout stays unchanged. Use
`CLICKHOUSE_PATTERN_WORKSPACES` when you only need to discover additional,
read-only workspace roots.

Use `just setup` once to install the repository's agent skills, then ask an
LLM to use the authoring skill. In Codex, paste this prompt:

```text
Use $clickhouse-pattern-author to create a workspace pattern for <describe the
system or feature>. Start from a suitable existing pattern if one fits;
otherwise create a new one. Define the data flow, documentation, and the
Docker-based runtime needed to validate it. Keep the curated patterns unchanged.
```

In Claude Code, use `/clickhouse-pattern-author` instead. The companion
`clickhouse-pattern-lab` skill can run, inspect, reload, and validate a runnable
pattern as it evolves.

## Documentation

- [Getting started](docs/getting-started.md): full workflow, local clones, live
  inspection, agent setup, and pattern discovery
- [Pattern Explorer architecture](docs/pattern-explorer.md)
- [Outstanding pattern proposals](docs/proposals/outstanding-patterns.md)
