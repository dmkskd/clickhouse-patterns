# S3Queue in ordered mode (filename watermark)

Profiles: `s3queue`, `s3`. Driver: `ch-s3q`.

Where the [s3() patterns](../s3-bulk-load/) have an external system trigger each
load, the [S3Queue engine](https://clickhouse.com/docs/engines/table-engines/integrations/s3queue)
puts the loop inside ClickHouse. It watches a prefix, processes each new file
exactly once, and a materialized view moves the rows into a MergeTree. This
pattern uses **ordered** mode; [s3queue-unordered](../s3queue-unordered/) is the
other mode.

```
file producer --drop--> S3: queue/*.parquet
                              |
             S3Queue ordered (watermark in Keeper)
                              |
                        events_mv --> demo.events
```

## The watermark, and what it skips

Ordered mode stores a single **watermark** in Keeper, the highest
filename processed. A file whose name sorts *after* the watermark is picked up; a
file that lands with an *earlier* name is skipped, because the watermark has
already moved past it. That keeps the state tiny, and it works when files are
written in lexical order (a timestamp or sequence in the name).

A writer with **key-order jitter**, meaning files that land minutes out of
order, loses the late ones, and there is no clean way to recover them.
Recovery re-reads a range of the prefix from a starting point, which re-ingests
the files already loaded in that range, so a full re-read duplicates the whole
dataset, and a new consumer that **starts after a chosen key** only narrows the
duplication to the recovery window. To recover without duplicates, point it at a
deduplicating target ([s3-versioned-upsert](../s3-versioned-upsert/)); to avoid
skips entirely, use [s3queue-unordered](../s3queue-unordered/).

`load.py` drops three in-order files into `queue/`; nothing triggers a load. The
engine picks them up and `_file` records each row's source, so
`uniqExact(source_file)` is 3.

## When to choose it

Filenames encode time or sequence and arrive roughly in order, and the tracking
state should stay as small as possible. For out-of-order arrivals, use unordered; for an
externally driven load, use the [s3() bulk load](../s3-bulk-load/).

```bash
just test s3queue-ordered
```

## Reference

- [S3Queue table engine](https://clickhouse.com/docs/engines/table-engines/integrations/s3queue)
- [S3 ClickPipes: ordered vs unordered ingestion](https://clickhouse.com/docs/integrations/clickpipes/object-storage/amazon-s3/overview)
  (the managed cloud equivalent)
