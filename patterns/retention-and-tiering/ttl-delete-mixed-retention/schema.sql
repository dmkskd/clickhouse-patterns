CREATE DATABASE IF NOT EXISTS demo;

-- multiIf chooses a deterministic retention period from each log level. The
-- table TTL then acts on the resulting expiry timestamp.
CREATE TABLE demo.events
(
    event_time DateTime,
    log_level LowCardinality(String),
    id UInt64,
    payload String,
    expires_at DateTime MATERIALIZED multiIf(
        log_level = 'DEBUG', event_time + INTERVAL 1 DAY,
        log_level = 'INFO',  event_time + INTERVAL 7 DAY,
        event_time + INTERVAL 30 DAY
    )
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, id)
TTL expires_at DELETE
SETTINGS merge_with_ttl_timeout = 1;

-- This leaves the default ttl_only_drop_parts = 0. The demonstration keeps
-- DEBUG and INFO rows in one part, so DELETE TTL rewrites that part to retain
-- the INFO rows after the DEBUG rows expire.
