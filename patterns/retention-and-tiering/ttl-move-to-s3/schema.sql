CREATE DATABASE IF NOT EXISTS demo;

CREATE TABLE demo.tiered_events
(
    event_time DateTime,
    id UInt64,
    payload String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, id)
TTL event_time + INTERVAL 30 DAY TO VOLUME 'cold'
SETTINGS storage_policy = 'tiered';
