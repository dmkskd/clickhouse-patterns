-- StorageKafka2 with static partition-to-shard affinity. Keeper coordinates the
-- ON CLUSTER DDL and, unlike the classic Kafka engine, also stores the committed
-- offsets and the partition locks that give each shard its own partitions.
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

-- kafka_keeper_path + kafka_replica_name select the experimental StorageKafka2
-- engine. kafka_partition_shard_num (from the {shard} macro) and kafka_shard_count
-- make each shard consume only the partitions where
-- partition_id % kafka_shard_count == kafka_partition_shard_num - 1, so shard 1
-- reads partitions 0 and 2 while shard 2 reads 1 and 3. Both shards share one
-- kafka_keeper_path; the engine suffixes it with the shard number so only
-- same-shard replicas compete for the same partition locks.
CREATE TABLE demo.events_queue ON CLUSTER sharded
(
    id   UInt64,
    kind String
)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094',
         kafka_topic_list  = 'events',
         kafka_group_name  = 'v2_affinity',
         kafka_format      = 'JSONEachRow',
         kafka_num_consumers = 1,
         kafka_keeper_path  = '/clickhouse/kafka/{database}/events_queue',
         kafka_replica_name = '{replica}',
         kafka_partition_shard_num = '{shard}',
         kafka_shard_count = 2;

-- No partition filter here: the engine already narrowed this shard to its own
-- partitions, so the view just copies every consumed row into the local table.
CREATE MATERIALIZED VIEW demo.events_mv ON CLUSTER sharded
TO demo.events AS
SELECT id, kind
FROM demo.events_queue;
