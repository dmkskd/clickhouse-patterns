CREATE DATABASE IF NOT EXISTS demo;

CREATE TABLE demo.recompressed_metrics
(
    -- Keep the column-specific encoding, but let RECOMPRESS TTL choose the
    -- general-purpose codec named by Default as the part gets older.
    event_time DateTime CODEC(Delta, Default),
    id UInt64,
    metric_name LowCardinality(String),
    value Float64 CODEC(Gorilla, Default),
    payload String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, id)
TTL event_time + INTERVAL 30 DAY RECOMPRESS CODEC(ZSTD(1))
SETTINGS merge_with_recompression_ttl_timeout = 1;

-- The TTL rule is table-level and runs for a whole eligible part. `Default`
-- lets the DateTime and Float64 columns preserve Delta and Gorilla while their
-- final codec changes from the hot default to ZSTD(1). A hard-coded column
-- codec, such as CODEC(Delta, LZ4), has higher priority and is not changed.
--
-- One second is only for this demonstration. In production the default
-- recompression TTL cooldown is four hours unless deliberately changed.
