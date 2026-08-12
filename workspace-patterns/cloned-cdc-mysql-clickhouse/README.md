# CDC: MySQL to ClickHouse (Altinity lightweight sink)

Profiles: `cdc-ch`, `mysql`, `cdc-mysql`. Driver: `ch-cdc`.

The [Altinity ClickHouse Sink Connector](https://github.com/Altinity/clickhouse-sink-connector)
runs in lightweight mode with embedded Debezium. One test compares three ways
to define the ClickHouse target without starting additional connectors.

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

ClickHouse creates `test.orders_existing` before the connector starts. It
demonstrates a controlled but compatible schema:

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

## Run

```bash
just test cdc-mysql-clickhouse
```

The connector uses a dedicated `cdc` ClickHouse user and stores offsets and
schema history in `altinity_sink_connector`. The pinned ClickHouse 25.3 image is
required by the JDBC version bundled in this connector release.
