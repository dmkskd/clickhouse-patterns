# Kafka ingestion: shared consumer group into a replicated table

Profiles: `cluster`, `kafka`. Driver: `ch-01`.

A Kafka engine table consumes a topic, a materialized view forwards each row into
a ReplicatedMergeTree, and Keeper replicates it to the second node.

```
topic "events" -> demo.events_queue (Kafka) -MV-> demo.events (ReplicatedMergeTree)
                  on ch-01 / ch-02                 ch-01 <-> Keeper <-> ch-02
```

## Run

```bash
just test kafka-ingest-replicated
just start kafka-ingest-replicated  # prepare the pattern and inspect it live
```

## Checks

1. Only the `cluster` and `kafka` profiles start; the `single` and `s3`
   profiles remain inactive.
2. `compose up --wait` blocks on Keeper/CH/Kafka healthchecks before any SQL runs.
3. After producing 20000 messages, the driver is polled until it has 20000
   rows, 20000 distinct IDs, and the exact ID bounds `0..19999` (Kafka
   consumption is asynchronous, so no healthcheck can express it).
4. The same exact-data check is asserted on ch-02, confirming replication
   without hiding a missing ID behind a duplicate.
5. The deterministic output check also verifies the three per-kind counts.

## Notes

- The Kafka table uses the broker's internal listener (`kafka:9094`); the
  producer uses the external one (`localhost:9092`). Same broker, two listeners.
- Both replicas share one `kafka_group_name`, so partitions are split across
  them. A consumer inserts its assigned messages into its local
  ReplicatedMergeTree, which uses Keeper to replicate the resulting parts to
  the peer.
- The cluster has `internal_replication=true`, but that controls writes through
  a Distributed table. This pattern has no Distributed table and does not rely
  on that setting for Kafka work-sharing or ReplicatedMergeTree replication.
- Selecting from a Kafka engine table consumes; query the MergeTree, not the
  queue.
- Delivery is at-least-once. For deduplication options see
  [kafka-push-exactly-once](../kafka-push-exactly-once/) and the
  `kafka-ingest-sharded-*` patterns.

## Production boundaries

- The auto-created topic has one partition, so one group member consumes at a
  time. The second ClickHouse consumer provides failover, not parallel ingest.
- The classic Kafka engine cannot atomically commit a ClickHouse insert and its
  Kafka offset. Retries can therefore duplicate rows, and `ORDER BY id` does
  not enforce uniqueness.
- A production deployment also needs an explicit partitioned and replicated
  topic, malformed-message handling, authentication/TLS, lag and replication
  monitoring, and an intentional partitioning and retention policy.
