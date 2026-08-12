-- One shared schema. Every shard gets the same objects, while {shard} expands
-- to a different Kafka consumer group on each server.
CREATE DATABASE IF NOT EXISTS demo ON CLUSTER sharded;

CREATE TABLE demo.events ON CLUSTER sharded
(
    id   UInt64,
    kind String
)
ENGINE = ReplacingMergeTree
ORDER BY id;

-- Read-only cluster-wide query facade. Cross-shard dedup is still a query
-- responsibility; Distributed does not deduplicate rows.
CREATE TABLE demo.events_all ON CLUSTER sharded
(
    id   UInt64,
    kind String
)
ENGINE = Distributed(sharded, demo, events);

CREATE TABLE demo.events_queue ON CLUSTER sharded
(
    id   UInt64,
    kind String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094',
         kafka_topic_list  = 'events',
         kafka_group_name  = 'w2_s{shard}',
         kafka_format      = 'JSONEachRow',
         kafka_num_consumers = 1;

CREATE MATERIALIZED VIEW demo.events_mv ON CLUSTER sharded
TO demo.events AS
SELECT id, kind FROM demo.events_queue;
