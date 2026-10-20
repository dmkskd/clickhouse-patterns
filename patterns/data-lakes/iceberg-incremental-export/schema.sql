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
