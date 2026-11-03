# ClickHouse Pattern Explorer

## Overview

To see it live, browse the hosted catalog at
[dmkskd.github.io/clickhouse-patterns](https://dmkskd.github.io/clickhouse-patterns/):

ClickHouse is a fast and flexible analytics engine. It offers several table
engine families and multiple ways to ingest, process, replicate, and distribute
data.

For many ClickHouse systems, query speed is not the main design challenge. The
harder part is choosing and combining the right building blocks for ingestion,
data modelling, delivery guarantees, replay and backfills, and cluster topology.

This repository is a catalog of runnable patterns for those choices, covering
ingestion, output, CDC, replication, and sharding. Each pattern starts the
services it needs, loads test data, and checks that it worked as expected.

## Run patterns locally

Requires Docker, [`uv`](https://docs.astral.sh/uv/), and [`just`](https://just.systems/).

```bash
git clone https://github.com/dmkskd/clickhouse-patterns.git
cd clickhouse-patterns
just setup      # install the Pattern Explorer and agent integrations
just explore    # open the catalog at http://localhost:8765
```

`just explore` opens the Pattern Explorer, a browser UI for the catalog. Each pattern
shows a resource diagram and trade-offs. Its services start from the browser as local
Docker Compose containers, and a SQL console and live table metadata are available
while they run.

See [Getting started](docs/getting-started.md) for the command line, live
inspection, and agent setup.

## Create custom patterns

A team can describe its own architecture, or a proposed one, as a pattern with
the same diagram and trade-offs as the catalog, and validate it once it has a runtime.

`just new` creates a `pattern.yaml` with a placeholder description and diagram,
and no services to run. `just clone` copies a runnable pattern as a starting point.

To fill in the pattern, ask an agent to use the `clickhouse-pattern-author` skill.
It writes the diagram, trade-offs, and references. For a runnable pattern, it
combines services from a shared Docker Compose stack
([`compose/stack.yml`](compose/stack.yml)) and adds the schema, load, and
verification steps:

- ClickHouse: single node, replicated cluster, or shards
- Sources and sinks: Kafka, Kafka Connect, PostgreSQL, MySQL, S3 (MinIO)
- CDC: PeerDB, Altinity Sink Connector, walshadow

See [Workspace patterns](docs/getting-started.md#workspace-patterns).

## Documentation

- [Getting started](docs/getting-started.md): command line, workspace patterns,
  live inspection, agent setup, and pattern discovery
- [Pattern Explorer architecture](docs/pattern-explorer.md): static catalog
  (`just site`, `just build-single`) and local control
- [Outstanding pattern proposals](docs/proposals/outstanding-patterns.md)
