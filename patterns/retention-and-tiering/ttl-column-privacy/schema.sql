CREATE DATABASE IF NOT EXISTS demo;

-- Column TTL keeps the event row but replaces expired values with their type
-- default. For String columns that default is the empty string.
CREATE TABLE demo.access_events
(
    event_time DateTime,
    id UInt64,
    status LowCardinality(String),
    client_ip String TTL event_time + INTERVAL 30 DAY,
    user_agent String TTL event_time + INTERVAL 30 DAY
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, id)
SETTINGS merge_with_ttl_timeout = 1;

-- One second is only for this demonstration. Production uses the default
-- four-hour TTL-merge cooldown unless it is deliberately changed.
