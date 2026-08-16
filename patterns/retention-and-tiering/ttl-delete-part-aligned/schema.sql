CREATE DATABASE IF NOT EXISTS demo;

-- One retention period for every row. Partitioning by the event month keeps the
-- expired batch and the current batch in separate parts.
CREATE TABLE demo.events
(
    event_time DateTime,
    batch LowCardinality(String),
    id UInt64,
    payload String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, id)
TTL event_time + INTERVAL 30 DAY DELETE
SETTINGS
    -- The default (`0`) can rewrite a mixed-expiry part to retain live rows.
    -- With `1`, ClickHouse drops a part only after all of its rows have expired.
    ttl_only_drop_parts = 1,
    -- One second only makes the runnable demo converge quickly. Production
    -- defaults to 14,400 seconds and deletion still shares merge capacity.
    merge_with_ttl_timeout = 1;
