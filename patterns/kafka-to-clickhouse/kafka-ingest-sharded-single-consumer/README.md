# Sharded Kafka ingestion: one consumer routes rows to shards

Profiles: `shards`, `kafka`. Driver: `ch-s1`.

Because the [Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)
cannot pin a partition to a specific shard, this workaround
([ClickHouse#107832](https://github.com/ClickHouse/ClickHouse/issues/107832))
avoids multi-shard assignment entirely. A single consumer on one shard reads the
whole topic and routes each row to its owning shard through a Distributed table.

## One consumer, routed by consistent hash

The local storage and Distributed facade are created everywhere `ON CLUSTER
sharded`, but the Kafka table and its view omit `ON CLUSTER`, so only the driver
shard consumes. Its view writes to the Distributed table, which routes each row by
`cityHash64(id)`:

```sql
-- ch-s1 only
CREATE MATERIALIZED VIEW events_mv TO events_all AS   -- events_all is Distributed
SELECT id, kind FROM events_queue;
-- ch-s2 has no Kafka table; it only receives routed rows
```

Each event is read once and stored once; the sharding is consistent-hash, nothing
Kafka-specific beyond a single node holding the consumer.

## When to choose it

When each event should be read and stored once without the N-times cost of the
other two workarounds. The cost is a single point of ingestion: `ch-s2` has no
consumer, so if `ch-s1` is down ingestion stops cluster-wide, throughput cannot
scale past one shard, and each row takes an extra network hop through the
Distributed table. The native
[sharded-partition-affinity](../kafka-ingest-sharded-partition-affinity/) removes
the single point without those costs.

```bash
just test kafka-ingest-sharded-single-consumer
```

```
physical  distinct_ids
8000      8000
```

## Reference

- [ClickHouse Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)
- [ClickHouse#107832](https://github.com/ClickHouse/ClickHouse/issues/107832), the three sharded workarounds
