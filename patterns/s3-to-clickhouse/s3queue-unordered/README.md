# S3Queue in unordered mode (processed-file set)

Profiles: `s3queue`, `s3`. Driver: `ch-s3q`.

The same [S3Queue engine](https://clickhouse.com/docs/engines/table-engines/integrations/s3queue)
as [s3queue-ordered](../s3queue-ordered/), in **unordered** mode. Instead of a
watermark, it keeps the full set of processed files in Keeper, so it ingests every
new file regardless of name order.

```
file producer --drop (any order)--> S3: queue/*.parquet
                              |
             S3Queue unordered (processed set in Keeper)
                              |
                        events_mv --> demo.events
```

## Why unordered

Ordered mode's watermark skips files that land out of lexical order, so a writer
with key-order jitter loses them. Unordered mode tracks the **set** of processed
files, so order is irrelevant. A file that sorts before an already-processed one
is still ingested. The cost is that the set grows and must be bounded with
`s3queue_tracked_files_limit` and a TTL, where ordered kept only a single
watermark.

The managed cloud version (S3 ClickPipes) does the same with **S3 event
notifications**: it processes any file it is notified about, and only ignores edits
to files already ingested.

`load.py` drops three files into `queue/`; the engine ingests each exactly once,
and `_file` records the source, so `uniqExact(source_file)` is 3.

## When to choose it

When files do not arrive in key order (jittered writers, backfills, many
producers). Use [ordered](../s3queue-ordered/) when names are ordered and the
tracking state should stay small, or the [s3() bulk load](../s3-bulk-load/) for an
externally driven, one-off load.

```bash
just test s3queue-unordered
```

## Reference

- [S3Queue table engine](https://clickhouse.com/docs/engines/table-engines/integrations/s3queue)
- [S3 ClickPipes: continuous ingestion in any order](https://clickhouse.com/docs/integrations/clickpipes/object-storage/amazon-s3/overview#continuous-ingestion-any-order)
