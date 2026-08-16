# Bulk load from S3 with the s3() table function

Profiles: `single`, `s3`. Driver: `ch`.

Loading data from S3 is a single INSERT with the
[s3() table function](https://clickhouse.com/docs/sql-reference/table-functions/s3).
A glob in the path reads every matching file at once, which is how one INSERT
scales from a single file to a batch. This is the documented starting point; it
appends, with no deduplication or tracking of what was already loaded.

```
orchestrator --stage 3 files--> S3: events/batch-00{1,2,3}.parquet
                                          |
                 INSERT INTO events FROM s3('.../events/*.parquet')
                                          v
                                  demo.events (MergeTree)
```

## Loading many files with a glob

`load.py` stages three Parquet files under `events/`, then loads them all in one
statement:

```sql
INSERT INTO demo.events
SELECT id, kind FROM s3('http://minio:9000/clickhouse/events/*.parquet', 'Parquet');
```

The glob (`*`, and also `?`, `{a,b}`, `{N..M}`) matches every file, and the reads
parallelize across them. `SELECT count()` returns 3000.

## When to choose it

For a one-off or externally scheduled import where re-running the exact same load
is not a concern. The load is not idempotent and does not track ingestion state,
so re-running appends the rows again, and files that arrive later are not picked
up.
For rows that need deduplication or corrections on re-load, use a stable key
with a versioned `ReplacingMergeTree` target. To load only new files
continuously, use [s3queue-ingest](../s3queue-ingest/).

```bash
just test s3-bulk-load
```

## Reference

- [Integrating S3 with ClickHouse](https://clickhouse.com/docs/integrations/s3)
- [s3 table function](https://clickhouse.com/docs/sql-reference/table-functions/s3)
