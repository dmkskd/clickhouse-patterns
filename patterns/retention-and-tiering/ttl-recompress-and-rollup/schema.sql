CREATE DATABASE IF NOT EXISTS demo;

CREATE TABLE demo.recompressed_metrics
(
    event_time DateTime,
    id UInt64,
    metric_name LowCardinality(String),
    value Float64,
    payload String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, id)
TTL event_time + INTERVAL 30 DAY RECOMPRESS CODEC(ZSTD(1))
SETTINGS merge_with_recompression_ttl_timeout = 1;

-- One second is only for this demonstration. In production the default
-- recompression TTL cooldown is four hours unless deliberately changed.
