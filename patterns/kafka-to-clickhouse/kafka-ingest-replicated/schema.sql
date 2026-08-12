-- Streaming ingestion: Kafka engine table -> materialized view -> ReplicatedMergeTree.
-- Everything is created ON CLUSTER so both replicas get the DDL.

CREATE DATABASE IF NOT EXISTS demo ON CLUSTER patterns;

-- Durable target. A Kafka consumer inserts into its local replica, and the
-- ReplicatedMergeTree copies the resulting data parts to the peer via Keeper.
CREATE TABLE demo.events ON CLUSTER patterns
(
    id   UInt64,
    kind String,
    ts   DateTime DEFAULT now()
)
ENGINE = ReplicatedMergeTree
ORDER BY id;

-- The queue: a Kafka consumer surfaced as a table. Reading from it consumes.
CREATE TABLE demo.events_queue ON CLUSTER patterns
(
    id   UInt64,
    kind String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094',
         kafka_topic_list  = 'events',
         kafka_group_name  = 'ch_events',
         kafka_format      = 'JSONEachRow',
         kafka_num_consumers = 1;

-- The pump: forwards every consumed row into the durable table.
CREATE MATERIALIZED VIEW demo.events_mv ON CLUSTER patterns
TO demo.events AS
SELECT id, kind FROM demo.events_queue;
