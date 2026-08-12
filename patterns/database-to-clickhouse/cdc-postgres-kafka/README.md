# CDC: Postgres WAL to Kafka to ClickHouse

Profiles: `single`, `postgres`, `kafka`, `connect`. Driver: `ch`.

Level 5 of this group. It is the only one here that publishes the change stream
somewhere other consumers can read it.

```text
public.orders --WAL--> Debezium source --> pg.public.orders --> ClickHouse Sink --> test.orders
 (Postgres)            (Kafka Connect)        (topic)          (Kafka Connect)
                                                 |
                                                 `--> other consumers
```

Both connectors run on the same Kafka Connect worker. That is a realistic
single-cluster layout and it keeps the service count at two beyond ClickHouse
and the source.

## Why the broker

A direct connector delivers changes to ClickHouse and nowhere else. Adding a
second destination then means a second connector, a second replication slot, and
a second read of the same WAL. With a topic in between, a search index, a cache
invalidator, an audit store, or another team's service subscribes as its own
consumer group and reads the same records at its own pace. Postgres does not
notice, because the number of slots stays at one.

This is the pattern for an organisation where the change stream has more than
one customer. Where ClickHouse genuinely is the only destination,
[cdc-mysql-clickhouse](../cdc-mysql-clickhouse/) does the same job with one
service and no retention to manage.

Topic retention also decouples the two halves. A ClickHouse outage is absorbed
by the broker rather than stalling the WAL reader, so the replication slot keeps
advancing and Postgres does not accumulate WAL.

## The two transforms

Debezium publishes an envelope with `before`, `after`, `op`, and `source`
blocks. `ExtractNewRecordState` flattens it on the source side, before anything
is published:

| setting | effect |
|---|---|
| `delete.handling.mode=rewrite` | a delete becomes the key plus `__deleted` |
| `add.fields=lsn` | carries the LSN through as `__lsn`, used for ordering |
| `drop.tombstones=true` | suppresses the null-value tombstone record |

Every consumer therefore reads flat rows rather than envelopes. This stage does
not exist in the single-process patterns, because with no broker between extract
and apply a transform has no place to run, which is why both
[cdc-mysql-clickhouse](../cdc-mysql-clickhouse/) and
[cdc-postgres-peerdb](../cdc-postgres-peerdb/) do all their shaping inside
ClickHouse instead.

The second transform runs on the sink. `InsertField` adds the record's Kafka
coordinates, and `topic.field`, `partition.field` and `offset.field` are
available only to a sink connector, so this cannot be done upstream.

## Kafka metadata in the table

`__topic`, `__partition`, `__offset` and `__timestamp` are stored alongside the
row, which makes any row traceable to the exact record that produced it at very
little storage cost.

```sql
__topic     LowCardinality(String),
__partition UInt32        CODEC(DoubleDelta, ZSTD(1)),
__offset    UInt64        CODEC(DoubleDelta, ZSTD(1)),
__timestamp DateTime64(3) CODEC(DoubleDelta, ZSTD(1))
```

Within a block the topic is constant, the partition is constant or nearly so,
and offsets increase by one, so `DoubleDelta` reduces them to almost nothing.

Note that the official sink does not supply these columns itself; the docs cover
only `KeyToValue` for the record key. They come from Kafka Connect's own
`InsertField` transform.

## Current state

The target is a `ReplacingMergeTree(__lsn)`, so the highest LSN per `id` wins.
Deletes arrive as rewritten records carrying `__deleted = 'true'` and are
filtered on read rather than removed, so the table keeps a record that the row
was deleted.

Non-key columns are nullable because Postgres' default replica identity sends
only the key for a delete. Setting `REPLICA IDENTITY FULL` on the source table
would carry the full before-image and allow non-null columns, at the cost of
larger WAL records.

## Other connectors for the same shape

The sink here is the official
[ClickHouse Kafka Connect Sink](https://clickhouse.com/docs/integrations/kafka/clickhouse-kafka-connect-sink).
Anything that can consume the topic could take its place. Two worth naming:

- The [Altinity sink in Kafka mode](https://github.com/Altinity/clickhouse-sink-connector/blob/develop/doc/quickstart_kafka.md)
  is the same product used by [cdc-mysql-clickhouse](../cdc-mysql-clickhouse/),
  running as a Kafka Connect plugin instead of embedding Debezium in its own
  process. It consumes Debezium envelopes directly, so the unwrap transform
  configured here is not needed.
- The [Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)
  inverts the second half: ClickHouse consumes the topic itself rather than
  being written to. That removes the sink connector but moves consumer-group
  management inside ClickHouse. The `kafka-to-clickhouse` group covers it.

## Run

```bash
just test cdc-postgres-kafka
```
