-- One shared schema. Keeper coordinates DDL only; the data remains sharded
-- across two independent MergeTree tables.
CREATE DATABASE IF NOT EXISTS demo ON CLUSTER sharded;

CREATE TABLE demo.events ON CLUSTER sharded
(
    id   UInt64,
    kind String
)
ENGINE = MergeTree
ORDER BY id;

-- Read-only cluster-wide query facade. It stores no rows itself.
CREATE TABLE demo.events_all ON CLUSTER sharded
(
    id   UInt64,
    kind String
)
ENGINE = Distributed(sharded, demo, events);

-- Kafka expands {shard} from each server's macros, producing the distinct
-- consumer groups w1_s1 and w1_s2 from this single statement.
CREATE TABLE demo.events_queue ON CLUSTER sharded
(
    id   UInt64,
    kind String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094',
         kafka_topic_list  = 'events',
         kafka_group_name  = 'w1_s{shard}',
         kafka_format      = 'JSONEachRow',
         kafka_num_consumers = 1;

-- Four topic partitions are split into two contiguous ranges. getMacro()
-- evaluates locally, so shard 1 keeps 0,1 and shard 2 keeps 2,3.
CREATE MATERIALIZED VIEW demo.events_mv ON CLUSTER sharded
TO demo.events AS
SELECT id, kind
FROM demo.events_queue
WHERE intDiv(_partition, 2) + 1 = toUInt64(getMacro('shard'));
