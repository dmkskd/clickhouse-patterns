CREATE DATABASE IF NOT EXISTS demo;

-- `service, hour` is the primary-key prefix required by GROUP BY TTL. The
-- aggregate columns begin with each raw request's own values, then the TTL
-- merge replaces them with the hourly count, total, and maximum.
CREATE TABLE demo.hourly_request_metrics
(
    event_time DateTime,
    service LowCardinality(String),
    hour DateTime MATERIALIZED toStartOfHour(event_time),
    requests UInt64 DEFAULT 1,
    bytes UInt64,
    max_bytes UInt64 DEFAULT bytes
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (service, hour, event_time)
TTL event_time + INTERVAL 7 DAY
    GROUP BY service, hour
    SET
        requests = sum(requests),
        bytes = sum(bytes),
        max_bytes = max(max_bytes)
SETTINGS merge_with_recompression_ttl_timeout = 1;

-- One second is only for this demonstration. Production uses the default
-- four-hour recompression-TTL cooldown unless it is deliberately changed.
