# Sharded Kafka ingestion: each shard natively owns its partitions (experimental)

Profiles: `shards-v2`, `kafka`. Driver: `ch-s1v2`.

The native answer to the three workarounds in
[ClickHouse#107832](https://github.com/ClickHouse/ClickHouse/issues/107832), added
by [ClickHouse#108886](https://github.com/ClickHouse/ClickHouse/pull/108886): each
shard consumes only the partitions it owns, so no shard reads a partition it does
not need and there is no single ingestion point.

> **Experimental.** This uses StorageKafka2, which the docs mark as not production
> ready. It only exists in nightly master builds (merged after 26.7), so this
> pattern runs on the `clickhouse/clickhouse-server:head` image, not the pinned
> release the other Kafka patterns use.

## Static affinity via StorageKafka2

StorageKafka2 stores offsets in Keeper, selected by `kafka_keeper_path` and
`kafka_replica_name` and gated by `allow_experimental_kafka_offsets_storage_in_keeper`
(set in the shared `users.xml`). Two settings turn on static affinity:

```sql
CREATE TABLE events_queue ON CLUSTER sharded (id UInt64, kind String)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'events',
         kafka_group_name  = 'v2_affinity', kafka_format = 'JSONEachRow',
         kafka_keeper_path  = '/clickhouse/kafka/{database}/events_queue',
         kafka_replica_name = '{replica}',
         kafka_partition_shard_num = '{shard}',   -- 1 on ch-s1v2, 2 on ch-s2v2
         kafka_shard_count = 2;
```

A shard consumes partition `p` only when `p % kafka_shard_count == shard_num - 1`,
so shard 1 owns partitions 0 and 2, shard 2 owns 1 and 3. The view carries no
`WHERE`: the engine already narrowed the partitions, so it just copies each row
into the local `MergeTree`. Both shards share one `kafka_keeper_path`; the engine
suffixes it with the shard number so only same-shard replicas contend for the same
partition locks.

## When to choose it

When each event should be stored once with no wasted reads and no single ingestion
point, and can run an experimental engine on a nightly build. Assignment is modulo
only, so the partition-to-shard map is fixed by the shard count. As with any
partition split, dedup holds only if the producer keys each logical event to a
single partition.

```bash
just test kafka-ingest-sharded-partition-affinity
```

```
shard  rows
1      4000
2      4000
```

## Compatibility

The affinity settings merged to `master` on 2026-08-03, after the `26.7` release,
so they are absent from the pinned image the stable `shards` patterns use. This
pattern pins the `head` image on dedicated `ch-s1v2` / `ch-s2v2` nodes (mirroring
how `ch-cdc` pins a separate release). Re-point it at a tagged release once the
feature ships.

## Reference

- [ClickHouse Kafka table engine: static partition-to-shard affinity](https://clickhouse.com/docs/engines/table-engines/integrations/kafka#static-partition-to-shard-affinity)
- [ClickHouse#107832](https://github.com/ClickHouse/ClickHouse/issues/107832) (the workarounds), [ClickHouse#108886](https://github.com/ClickHouse/ClickHouse/pull/108886) (this feature)
