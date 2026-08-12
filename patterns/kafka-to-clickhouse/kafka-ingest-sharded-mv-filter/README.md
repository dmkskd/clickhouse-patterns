# Sharded Kafka ingestion: each shard filters to its own partitions

Profiles: `shards`, `kafka`. Driver: `ch-s1`.

The [Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)
distributes partitions within a shared consumer group, but cannot pin a partition
to a specific ClickHouse shard. This is one of three workarounds for that gap
([ClickHouse#107832](https://github.com/ClickHouse/ClickHouse/issues/107832)):
each shard reads the whole topic under its own group, and a materialized view
keeps only the partitions it owns.

## Filtering on the partition column

`schema.sql` is applied `ON CLUSTER sharded`. Every shard consumes all partitions
under group `w1_s{shard}`, and its view filters on the `_partition` virtual column
so each event is stored on exactly one shard:

```sql
CREATE MATERIALIZED VIEW events_mv ON CLUSTER sharded TO events AS
SELECT id, kind FROM events_queue
WHERE intDiv(_partition, 2) + 1 = toUInt64(getMacro('shard'));
```

## When to choose it

When each event must be stored once across shards on the classic engine. The
cost is that every shard reads and decodes all 8000 messages to keep half, the
full Kafka read cost regardless of ownership, and the partition-to-shard map is
static, so changing the partition or shard count needs a deliberate mapping change.
The native alternative is
[sharded-partition-affinity](../kafka-ingest-sharded-partition-affinity/).

```bash
just test kafka-ingest-sharded-mv-filter
```

```
shard  rows
1      4000
2      4000
```

## Reference

- [ClickHouse Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)
- [ClickHouse#107832](https://github.com/ClickHouse/ClickHouse/issues/107832), the three sharded workarounds
