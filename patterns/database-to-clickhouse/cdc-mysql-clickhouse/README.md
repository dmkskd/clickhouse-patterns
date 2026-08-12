# CDC: MySQL binlog to Altinity lightweight sink to ClickHouse

Profiles: `cdc-ch`, `mysql`, `cdc-mysql`. Driver: `ch-cdc`.

The [Altinity ClickHouse Sink Connector](https://github.com/Altinity/clickhouse-sink-connector)
runs in lightweight mode with embedded Debezium. One test compares three ways
to define the ClickHouse target without starting additional connectors.

Level 3 of this group. Before reaching for a connector, check whether
[postgres-table-engine](../postgres-table-engine/) or
[postgres-refreshable-pull](../postgres-refreshable-pull/) already covers the
case; neither needs a connector or versioned reads. CDC justifies its extra services
when the table is too large to re-read on a schedule, when the staleness window
is too wide, or when the change history is itself the product.

## Why MySQL here

The connector is source-agnostic, so the same lightweight deployment runs
Debezium against MySQL binlogs or PostgreSQL `pgoutput`, and the three ClickHouse
target choices are identical either way. MySQL is used so that the group has exactly one
Postgres deployment story, in [cdc-postgres-peerdb](../cdc-postgres-peerdb/),
where two Postgres instances have to be told apart. Running this against
PostgreSQL means pointing the connector at the `postgres` service and switching
its Debezium connector class; nothing in `transform.sql` or the target DDL
changes, except that PostgreSQL's default replica identity emits only key data
for deletes, so non-key columns in the existing and transformed targets must stay
nullable.

## Compatibility

This pattern intentionally runs ClickHouse 25.3 with the
`altinity/clickhouse-sink-connector:2.9.1-lt` image. A control run on
2026-07-25 recorded the following.

- With ClickHouse 26.6.1.1193, the server completed the connector's JDBC
  startup metadata and `SELECT VERSION()` queries without server exceptions,
  but the connector logged `java.sql.SQLException: Query failed` while reading
  them. CDC did not start, `test.orders` was not created, and the pattern timed
  out after 120 seconds.
- With ClickHouse 25.3 restored, the same test passed all six convergence
  checks and matched the nine-row expected output.

The upstream 2.9.1 source
[bundles `clickhouse-jdbc` 0.6.5](https://github.com/Altinity/clickhouse-sink-connector/blob/999b63d712212502583b4efe41a84d760c161e6a/sink-connector-lightweight/pom.xml#L474-L480),
while its
[feature matrix says ClickHouse 24.8 and above is supported](https://github.com/Altinity/clickhouse-sink-connector/blob/999b63d712212502583b4efe41a84d760c161e6a/doc/feature_matrix.md#L3-L9).
No matching upstream issue was found, so this is recorded as a reproduced
compatibility discrepancy rather than a cited upstream limitation.

```text
MySQL orders -> Altinity sink -> test.orders
                                     |
                                     `-> MV -> test.orders_transformed

MySQL orders_existing -> Altinity sink -> test.orders_existing
```

## CDC-created table

`auto.create.tables: true` lets the connector create `test.orders` from the
source record schema. It uses `ReplacingMergeTree`, `_version`, and
`is_deleted`. Current-state reads use `FINAL` and exclude deletion markers.

## Transformation

Once the initial snapshot creates `test.orders`, `transform.sql` creates an
incremental materialized view and backfills the three snapshot rows. New CDC
versions then flow through the view in real time.

The transformation uppercases `customer`, converts `amount` to
`Decimal(12, 2)`, and derives `amount_band`. Its target retains `_version` and
`is_deleted`; dropping that metadata would make updates and deletes incorrect.

## Existing target table

ClickHouse creates `test.orders_existing` before the connector starts. It is a controlled but compatible schema.

- `customer` is `LowCardinality(Nullable(String))`;
- source `Int32` is widened to `Nullable(Int64)`;
- `amount_band` is an additional `MATERIALIZED` column;
- the connector's `_version` and `is_deleted` columns remain present.

Non-key columns are nullable because a MySQL delete event can carry absent
values. Connector DDL execution and schema evolution are disabled so the source
DDL cannot replace the chosen ClickHouse types. Auto-creation remains enabled
for the separate `orders` table.

The test snapshots both source tables, applies matching INSERT, UPDATE, and
DELETE operations, and compares the current state of all three ClickHouse
targets.

## Where the transformation happens

The lightweight connector does not run a transform chain. Its documented
configuration exposes routing and filtering (`database.include.list`,
`table.include.list`, `clickhouse.database.override.map`) and type-handling
knobs (`binary.handling.mode`, `persist.raw.bytes`), not per-message rewriting.
The Kafka Connect single-message transforms that people associate with Debezium
belong to the connector's
[Kafka deployment mode](https://github.com/Altinity/clickhouse-sink-connector/blob/develop/doc/architecture.md),
where a broker sits between extract and apply. Collapsing that into one process
removes the place an SMT would run.

All semantic work in this pattern therefore happens in ClickHouse, in two
different positions.

**At landing, in the target DDL.** `test.orders_existing` widens `amount`,
switches `customer` to `LowCardinality(Nullable(String))`, and declares a
`MATERIALIZED` classification column. ClickHouse evaluates these on the
connector's own insert, without an extra object or an extra pass.

**After landing, in a materialized view.** `transform.sql` uppercases
`customer`, casts `amount` to `Decimal(12, 2)`, and derives `amount_band` into
`test.orders_transformed`. This needs an explicit backfill for snapshot rows and
must carry `_version` and `is_deleted` through so updates and tombstones still
converge.

Prefer the DDL position when the change is a type or a derived column, and the
MV position when it is a rewrite or a reshape. The
[PeerDB pattern](../cdc-postgres-peerdb/) lands in the same place, for the same
reason.

[postgres-refreshable-pull](../postgres-refreshable-pull/) places the same three
transformations in the refreshable view's own `SELECT`, with no backfill and no
CDC metadata to carry, because a full replace never has two versions of a row to
reconcile. Tracking changes costs more on the read side than re-reading state.

## Run

```bash
just test cdc-mysql-clickhouse
```

The connector uses a dedicated `cdc` ClickHouse user and stores offsets and
schema history in `altinity_sink_connector`.
