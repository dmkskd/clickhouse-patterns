# Versioned upsert from S3 (deduplicate and correct by version)

Profiles: `single`, `s3`. Driver: `ch`.

Re-running the [bulk load](../s3-bulk-load/) appends the same rows a second
time. This pattern adds versioned deduplication so that re-loads and corrections
converge instead. Each row carries a `version` number and the target is a
`ReplacingMergeTree(version)`, which keeps the highest version per key. This is
the standard ClickHouse upsert, used by CDC tools such as PeerDB, Debezium, and
ClickPipes, and it requires a stable unique key.

```
batch 1 (version 1): 1000 events
batch 2 (version 2): corrects ids 0..99 to 'refund'
re-load batch 1    : cannot win, because version 1 < 2
```

## What the version is

The `version` only has to be **higher for newer data** and fixed in the staged
file. It can be a batch sequence, a timestamp, or the source log position (LSN).
PeerDB uses a nanosecond sync timestamp for `_peerdb_version` (its snapshot rows
are version `0`, so any later change supersedes them). Because the version travels
with the row in the file, re-loading a file re-inserts the same version and dedups
to a no-op.

## Order independence

`load.py` loads batch 1, then a corrective batch 2 (`refund` for ids 0..99 at
version 2), then **re-loads batch 1**. `FINAL` still shows the corrections,
because `ReplacingMergeTree(version)` keeps the highest version per id regardless
of load order:

```sql
SELECT count() AS rows, countIf(kind = 'refund') AS corrected
FROM demo.events FINAL;   -- 1000, 100
```

## When to choose it

When the source has a stable key and rows can be updated or re-sent. It does not
fit append-only or keyless data, which has no key to deduplicate on; for that,
track processed files with [s3queue-ingest](../s3queue-ingest/). Deletes fit the
same model by carrying an `is_deleted` flag on the latest version.

Two notes from CDC practice are worth adding. On large tables, reading with
`argMax(col, version) GROUP BY key` is cheaper than `FINAL`. For upserts plus
deletes with strict accounting, `VersionedCollapsingMergeTree` (a
sign column) is the alternative to `ReplacingMergeTree`.

```bash
just test s3-versioned-upsert
```

## Reference

- [ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)
- [PeerDB: ClickHouse data modeling](https://docs.peerdb.io/bestpractices/clickhouse_datamodeling)
  (`_peerdb_version`, `_peerdb_is_deleted`, `ReplacingMergeTree`)
- [s3 table function](https://clickhouse.com/docs/sql-reference/table-functions/s3)
