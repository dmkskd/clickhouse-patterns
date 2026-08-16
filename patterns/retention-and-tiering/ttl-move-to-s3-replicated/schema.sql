CREATE DATABASE IF NOT EXISTS demo ON CLUSTER patterns;

CREATE TABLE demo.replicated_tiered_events ON CLUSTER patterns
(
    event_time DateTime,
    id UInt64,
    payload String
)
ENGINE = ReplicatedMergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, id)
TTL event_time + INTERVAL 30 DAY TO VOLUME 'cold'
SETTINGS
    storage_policy = 'tiered',
    allow_remote_fs_zero_copy_replication = 0;
