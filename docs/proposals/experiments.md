# Experiments: on-demand workloads with parameters

## Motivation

`load` runs once per pattern start and must finish before `verify`. It cannot
run a workload repeatedly, vary its inputs, or compare results across inputs.

Commit `ea22365` added a probe loop to the walshadow `load.py`: 200 single-row
inserts at 50 per second into a `latency_probe` table. Commit `e50380e` removed
the loop and kept the `replication_latency_ms` column on the order rows. The
column measures the interval from the source write (`updated_at`) to the
ClickHouse insert (`ch_inserted_at`) for each CDC change.

One run at fixed inputs gives one latency distribution. The useful question is
how latency and cost change with the values each pattern exposes in `config/`.

## Exposed values in the database CDC patterns

| Pattern | File | Value | Current |
|---|---|---|---|
| `cdc-postgres-walshadow` | `config/latency.toml` | `[ch] flush_timeout_ms` | 1000 |
| `cdc-mysql-clickhouse` | `config/connector.yaml` | `poll.interval.ms`, `buffer.flush.time.ms` | 500, 30 |
| `cdc-postgres-kafka` | `config/source.json` | `poll.interval.ms` | 500 |
| `cdc-postgres-peerdb` | `config/mirror.sql` | `sync_interval` (seconds) | 1 |

All four compute `replication_latency_ms` on the replicated orders table, so
one metric compares settings within a pattern and the four tools against each
other.

## Running an experiment

An experiment is an explicit action against the active session. `run`,
`reload` and `validate` never start one. Two entry points:

- `just experiment` lists the experiments of the active pattern.
  `just experiment <name>` runs the full grid.
  `just experiment <name> rate=500 flush_timeout_ms=100` runs one grid point.
- The Explorer lists the same experiments for the active pattern, with the
  parameter values as editable fields and a **Run** button that calls
  `POST /api/session/experiment`. Progress streams through `/api/events` like
  `run` and `validate`. Results appear as a table, one row per grid point.

Only one operation runs at a time: an experiment takes the same session lock
as `run`, `reload` and `stop`.

## Declaring an experiment

```yaml
experiments:
  - name: replication-latency
    description: Source write to ClickHouse insert, per flush timeout and write rate.
    workload: experiments/replication_latency.py   # script in the pattern folder
    restart: walshadow           # service that reads the config file
    duration_s: 30
    parameters:
      flush_timeout_ms: [100, 500, 1000]   # placeholder in config/latency.toml
      rate: [50, 500]                      # workload argument
      rows_per_txn: [1, 100]               # workload argument
```

- **Workload per pattern.** Each pattern owns its workload script, like
  `load.py`. The walshadow script inserts and updates rows in Postgres
  `public.orders`; the MySQL script does the same in MySQL. The runner passes
  `run_id`, `duration_s` and the workload parameters as arguments. A small
  helper module provides the rate loop and the wait until ClickHouse holds
  every row the run wrote. `public.orders` has no `run_id` column; each script
  identifies its rows, for example by an id range.
- **Config parameters as placeholders.** A config file marks a value with
  `{{name:default}}`, for example `flush_timeout_ms = {{flush_timeout_ms:1000}}`.
  The syntax is the same in TOML, YAML, JSON and SQL. `run` and `reload`
  substitute the default, so a normal start is unchanged. A parameter that
  matches a placeholder is a config parameter; any other parameter is passed to
  the workload.
- **Results.** Each grid point records p50, p95 and p99 of
  `replication_latency_ms`, ClickHouse inserts and parts created
  (`system.part_log`, after `SYSTEM FLUSH LOGS`). The queries share the format
  of the `measure` entries in [measuring-metrics.md](measuring-metrics.md).

## Runner

For each grid point:

1. If a config parameter changed, render the file and restart the `restart`
   service. Grid points are ordered so each config value is applied once.
2. Run the workload with its arguments, `run_id` and `duration_s`.
3. Run the result queries with `run_id` and `started_at` bound as query
   parameters.
4. Insert one row into `_lab.experiment_runs`: pattern, experiment, run id,
   parameter values, results, start and end time.

## Open questions

- Restart cost differs per tool and must be checked before building:
  - walshadow mounts no volume, and its pattern notes say losing its state
    forces a full initial load. Each new config value would re-snapshot.
  - PeerDB creates the mirror with `CREATE MIRROR IF NOT EXISTS`, so a changed
    `sync_interval` may not apply to an existing mirror.
  - Restart behaviour of the MySQL lightweight connector and the Debezium
    source connector is not yet checked.
- Probe rows: the workload can write to the existing orders table or to a
  dedicated probe table. A probe table needs replication setup per tool. The
  walshadow entrypoint in `compose/stack.yml` registers only `public.orders`
  with `walshadow-stream init`; the pattern note mentions
  `replicate_all = true`, but no file in the repository sets it.
- Source and ClickHouse run in containers on one host and share its clock. On
  separate hosts the latency columns depend on clock synchronization.
- Whether `_lab.experiment_runs` survives `just stop`. Keeping results across
  sessions needs storage outside the pattern's volumes.
