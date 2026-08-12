# CDC: Postgres WAL to PeerDB to ClickHouse

Profiles: `single`, `postgres`, `s3`, `peerdb`. Driver: `ch`.

Level 4 of this group. This runs PeerDB locally as the open-source engine behind
managed Postgres ClickPipes. A single mirror captures two equivalent source
tables and compares three ClickHouse target choices.

## Two Postgres instances

They share an engine and nothing else. Confusing them makes the rest of this
pattern difficult to follow.

| | `postgres` | `peerdb-catalog` |
|---|---|---|
| Role | **Replication source** | **PeerDB control plane** |
| Owned by | the operator | PeerDB |
| Holds | `public.orders` and `public.orders_existing`, the user data | peers, mirror config, Temporal workflow history |
| Read by | PeerDB, through a logical replication slot | PeerDB and Temporal, as their own metadata store |
| User rows | yes, this is the data being replicated | **never** |
| Compose profile | `postgres` | `peerdb` |
| Volume | none (ephemeral) | `peerdb-catalog-data` |
| If replaced | something else would be replicated | nothing about the CDC path changes |

They need separate credentials, backups, and monitoring. Losing the source loses
the data; losing the catalog loses the mirror definitions and in-flight workflow
state, which means recreating the mirror and resnapshotting.

Everything below concerns the source.

```text
Postgres orders -> PeerDB -> test.orders
                                  |
                                  `-> MV -> test.orders_transformed

Postgres orders_existing -> PeerDB -> test.orders_existing
```

Initial snapshots pass through the PeerDB snapshot worker and MinIO. Later
changes flow from PostgreSQL's logical replication slot through the CDC worker
and use the same transient stage. PeerDB then issues the ClickHouse loads;
ClickHouse reads the named Avro objects from MinIO through its `s3()` table
function. Snapshot queries insert directly into the destination tables. Change
batches first land in PeerDB's mirror-wide `_peerdb_raw_two_table_mirror`
MergeTree, then PeerDB issues target-table inserts that decode the staged CDC
records, so ClickHouse never polls the bucket on its own.

That hand-off involves two separate network relationships.

```text
control: PeerDB -> ClickHouse     issues INSERT ... SELECT ... FROM s3(...)
data:    ClickHouse -> MinIO      requests the named object over HTTP
         MinIO -> ClickHouse      returns Avro bytes to the running query
```

MinIO plays no active part, since writing an object does not notify ClickHouse.
PeerDB's SQL request is the control-plane link that causes ClickHouse to fetch it.

## CDC-created table

PeerDB creates `test.orders`, maps the source types, and adds
`_peerdb_version`, `_peerdb_is_deleted`, and `_peerdb_synced_at`. Current-state
reads use `FINAL` and filter `_peerdb_is_deleted = 0`.

## Transformation

After the snapshot creates `test.orders`, `transform.sql` installs an
incremental materialized view and explicitly backfills the snapshot. It
uppercases `customer`, converts `amount` to `Decimal(12, 2)`, and derives
`amount_band`.

The transformed `ReplacingMergeTree` retains `_peerdb_version` and
`_peerdb_is_deleted`. This is a row-level transformation, not an incremental
current-state aggregate, so each incoming CDC version and tombstone must continue
to reach the target.

## Existing target table

`schema.sql` creates `test.orders_existing` before the mirror starts. The table
widens `amount` from `Int32` to `Int64`, changes `customer` to
`LowCardinality(String)`, and adds a `MATERIALIZED amount_band` column while
retaining PeerDB's required metadata.

This target must remain compatible with both PeerDB's snapshot encoding and its
streamed-change encoding. Semantic conversion to `Decimal` is intentionally in
the materialized-view transformation rather than the direct CDC target.

The two source tables receive matching INSERT, UPDATE, and DELETE operations.
`verify.sql` then reports the current state of all three paths together.

## Comparison with Altinity/Debezium

Surface differences:

| | PeerDB | Altinity lightweight sink |
|---|---|---|
| Snapshot staging | MinIO/S3 | Connector snapshot stream |
| Change source | PostgreSQL logical replication | Debezium (MySQL binlog there; `pgoutput` if pointed at Postgres) |
| Version column | `_peerdb_version` | `_version` |
| Delete column | `_peerdb_is_deleted` | `is_deleted` |

What the extra services actually buy:

| | PeerDB | Altinity lightweight sink |
|---|---|---|
| Services beyond ClickHouse and the source | 9 | 1 |
| Initial load | Split into row ranges and copied in parallel; a failure repeats only the unfinished ranges | A single embedded Debezium snapshot, restarted from the beginning on failure |
| Failure recovery | Resumes at the next unfinished step; a failed step retries on its own | Restart the process from the last flushed offset |
| Read vs write coupling | Separate steps joined by a staging table | One pipeline; a stalled destination reaches the WAL slot |
| Scale-out | Workers hold no state, so capacity is added by running more | One process per mirror |
| Load shape | Bulk `INSERT ... SELECT FROM s3()` over Avro | Row batches over JDBC |
| Extra stateful systems | Catalog Postgres, Temporal persistence | None; state lives in ClickHouse tables |
| Postgres instances to operate | 2 (source + catalog) | 1 (source only), or 0 with a MySQL source |
| ClickHouse version | Native + `s3()`, runs 26.7 | JDBC 0.6.5, pinned to 25.3 |

At this pattern's scale nothing in the right-hand column is a problem, and
nothing in the left-hand column is exercised. The two stacks produce identical
results on three rows. The divergence starts where a single Debezium process stops fitting in one
container's memory during the initial load, which is also where managed
ClickPipes becomes the practical answer.

## Where the transformation happens

Neither engine transforms in flight; both move rows as they are, add versioning
and tombstone metadata, and leave semantic work to ClickHouse.

PeerDB has no per-message transform hook on the CDC path. The step that writes
the targets decodes staged Avro into columns and evaluates no user expressions.
The uppercase, `Decimal` cast, and `amount_band` derivation in `transform.sql`
all run inside ClickHouse, in an incremental materialized view reading
`test.orders`, after the row has landed.

The `orders_existing` path shapes rows without a materialized view, in the
target's own DDL. Widening `amount` to `Int64`, using
`LowCardinality(String)`, and declaring `MATERIALIZED amount_band` are all
evaluated by ClickHouse at insert time, on the CDC insert itself. That is
transformation at landing rather than after it, and it costs nothing extra.

A Kafka Connect deployment differs structurally, because an SMT can rewrite each
message between source and sink, and removing the broker removes that stage.
[cdc-postgres-kafka](../cdc-postgres-kafka/) puts it back, and
[cdc-mysql-clickhouse](../cdc-mysql-clickhouse/) reaches the same conclusion.

## Cheaper options first

For a small table, [postgres-refreshable-pull](../postgres-refreshable-pull/)
produces the same current-state result with one DDL statement and no additional
services. A scheduled full replace never holds two versions of a row, so it also reads
without `FINAL`, a version column, or a tombstone filter. This pattern justifies
its nine extra services when the source is too large to re-read on a schedule,
when the staleness window is too wide, or when the change stream itself is the
requirement.

## Run

```bash
just test cdc-postgres-peerdb
```

To leave the result available to the ClickHouse MCP:

```bash
just start cdc-postgres-peerdb
just validate
```
