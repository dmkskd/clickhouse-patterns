# Sharded Kafka ingestion: each shard stores everything, deduplicate on read

Profiles: `shards`, `kafka`. Driver: `ch-s1`.

Because the [Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)
cannot pin a partition to a specific shard, this workaround
([ClickHouse#107832](https://github.com/ClickHouse/ClickHouse/issues/107832))
gives each shard its own consumer group. Each group reads all partitions, so
every shard stores the complete topic, and duplicates are resolved at read time.

## ReplacingMergeTree, deduplicated on read

`schema.sql` (applied `ON CLUSTER sharded`) stores everything into a
`ReplacingMergeTree`:

```sql
CREATE TABLE events (id UInt64, kind String)
ENGINE = ReplacingMergeTree ORDER BY id;
```

The dedup is a general ClickHouse technique, not Kafka-specific. It applies to any
duplicate-prone ingestion, including at-least-once delivery, retried inserts,
overlapping
backfills, an `s3()` reload run twice. Kafka is only the source of the duplicates
here.

## FINAL deduplicates per shard, not across

`ReplacingMergeTree` collapses duplicate `ORDER BY` keys within one table,
eventually on background merges; `FINAL` forces that collapsed view at query time.
It does not deduplicate across shards, so the cross-shard copies here are
resolved by a query-time `uniqExact(id)` over the Distributed table.

## When to choose it

When N is modest and keys are simple. The cost is N-times storage (2x here) and
dedup paid on every query: `FINAL` scans are heavier and merge work is unbounded.

```bash
just test kafka-ingest-sharded-full-copy
```

```
physical  distinct_ids
16000     8000
```

Every event is stored on both shards (16000 rows), 8000 distinct.

## Reference

- [ClickHouse Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)
- [ClickHouse#107832](https://github.com/ClickHouse/ClickHouse/issues/107832), the three sharded workarounds
