# Exactly-once push via the ClickHouse Sink

Profiles: `cluster`, `kafka`, `connect`. Driver: `ch-01`.

Same connector as [kafka-push-connect](../kafka-push-connect/), with
`exactlyOnce: true`, and a test that forces reprocessing to check the guarantee.

## Mechanism

With `exactlyOnce: true` the connector keeps a per-(topic, partition) high-water
mark in a `KeeperMap` table in ClickHouse. Before inserting a batch it checks the
mark and skips anything already applied. `KeeperMap` needs a Keeper connection
and `keeper_map_path_prefix` (set in `compose/config/cluster.xml`), so this runs
on the `cluster` profile rather than `single`.

## Test

`load.py`:

1. Ingest 8000 rows with `exactlyOnce: true`.
2. Stop the connector, delete its committed offsets, resume it. The consumer
   re-reads all 8000 records from offset 0.
3. Wait until the connector has re-committed offset 8000 (reprocessing done).

Assertions:

```
ch-01: count == 8000
ch-02: count == 8000     (replicated)
verify: 8000 rows / 8000 distinct
```

An at-least-once sink would show 16000 rows here, every record inserted twice.

## Comparison with the pull engine

The Kafka engine ([kafka-ingest-replicated](../kafka-ingest-replicated/)) is
at-least-once, because a rebalance or restart mid-batch re-reads uncommitted
messages and duplicates rows, so it needs a downstream dedup strategy. The Connect sink moves
that guarantee into the ingestion layer, keeping the target table clean.

## Notes

- `KeeperMap` is off by default. Without `keeper_map_path_prefix` the connector's
  state table fails to create and the task dies.
