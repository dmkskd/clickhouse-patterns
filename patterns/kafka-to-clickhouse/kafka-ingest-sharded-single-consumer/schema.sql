-- Shared storage exists on every shard. Keeper coordinates these DDL queries;
-- it does not replicate the MergeTree data.
CREATE DATABASE IF NOT EXISTS demo ON CLUSTER sharded;

CREATE TABLE demo.events ON CLUSTER sharded
(
    id   UInt64,
    kind String
)
ENGINE = MergeTree
ORDER BY id;

-- This facade is both the cluster-wide read surface and the write router.
-- cityHash64(id) selects the destination shard for every inserted row.
CREATE TABLE demo.events_all ON CLUSTER sharded
(
    id   UInt64,
    kind String
)
ENGINE = Distributed(sharded, demo, events, cityHash64(id));

-- These two objects deliberately omit ON CLUSTER. The schema is executed on
-- ch-s1, making it the pattern's single Kafka ingestion coordinator.
CREATE TABLE demo.events_queue
(
    id   UInt64,
    kind String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094',
         kafka_topic_list  = 'events',
         kafka_group_name  = 'w3',
         kafka_format      = 'JSONEachRow',
         kafka_num_consumers = 1;

CREATE MATERIALIZED VIEW demo.events_mv
TO demo.events_all AS
SELECT id, kind FROM demo.events_queue;
