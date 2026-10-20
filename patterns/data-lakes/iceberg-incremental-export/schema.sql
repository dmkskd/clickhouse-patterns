CREATE DATABASE IF NOT EXISTS demo;

-- Source: append-only events. The block number/offset columns give every row a
-- commit position, which APPEND INCREMENTAL uses as its cursor; the min/max
-- indexes on them let a refresh skip parts below the cursor.
CREATE TABLE demo.order_events
(
    event_id UInt64,
    event_time DateTime,
    order_id UInt64,
    event_type LowCardinality(String),
    country LowCardinality(String),
    amount Decimal(10, 2)
)
ENGINE = MergeTree
ORDER BY (event_time, order_id, event_id)
SETTINGS
    enable_block_number_column = 1,
    enable_block_offset_column = 1,
    add_minmax_index_for_block_number_column = 1,
    add_minmax_index_for_block_offset_column = 1,
    part_minmax_index_columns = 'with_block_number_offset';

-- Destination: an Iceberg table in MinIO. Development-only credentials.
CREATE TABLE demo.lake_order_events
(
    event_id UInt64,
    event_time DateTime,
    order_id UInt64,
    event_type String,
    country String,
    amount Decimal(10, 2)
)
ENGINE = IcebergS3('http://minio:9000/clickhouse/lake/order_events/', 'clickhouse', 'clickhouse_secret', 'Parquet');

-- Each refresh appends rows committed since the previous one and stores the
-- new cursor in the same Iceberg snapshot.
CREATE MATERIALIZED VIEW demo.order_events_to_iceberg
REFRESH EVERY 1 MINUTE APPEND INCREMENTAL
TO demo.lake_order_events
AS SELECT event_id, event_time, order_id, event_type, country, amount
FROM demo.order_events;

-- Row-by-row comparison of the source with the Iceberg table, read back from
-- MinIO with the icebergS3() table function. Iceberg has no unsigned types, so
-- event_id is read back as Int64 and cast for the join.
CREATE VIEW demo.lake_drift AS
SELECT
    coalesce(s.event_id, l.event_id) AS event_id,
    s.amount AS clickhouse_amount,
    l.amount AS iceberg_amount,
    multiIf(s.event_id IS NULL, 'deleted in source, still in Iceberg',
            l.event_id IS NULL, 'in source, not in Iceberg',
            s.amount != l.amount, 'updated in source, old value in Iceberg',
            'same') AS state
FROM demo.order_events AS s
FULL OUTER JOIN
(
    SELECT toUInt64(event_id) AS event_id, amount
    FROM icebergS3('http://minio:9000/clickhouse/lake/order_events/', 'clickhouse', 'clickhouse_secret')
) AS l ON s.event_id = l.event_id
SETTINGS join_use_nulls = 1;

-- The load step saves the comparison after each stage of the demo.
CREATE TABLE demo.drift_check
(
    stage UInt8,
    stage_name String,
    event_id UInt64,
    clickhouse_amount Nullable(Decimal(10, 2)),
    iceberg_amount Nullable(Decimal(10, 2)),
    state String
)
ENGINE = MergeTree
ORDER BY (stage, event_id);
