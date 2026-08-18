# Query-time aggregation (rollups computed on read)

Profiles: `single`. Driver: `ch`.

Level 1 of this group. The rollup is not stored at all; ClickHouse keeps the raw
ticks and computes the summary rows at query time.

```
loader --INSERT (3 batches)--> demo.ticks (MergeTree)
                                   |
        GROUP BY toStartOfMinute(ts) / toStartOfFiveMinutes(ts) on read
                                   v
                    1-minute and 5-minute rollups
```

## The rollups

The same raw table answers both a per-minute and a per-5-minute rollup, each computed
with a single `GROUP BY`:

```sql
SELECT symbol,
       toStartOfMinute(ts) AS bucket,   -- or toStartOfFiveMinutes(ts)
       argMin(price, ts)   AS open,     -- first price in the bucket, by time
       max(price)          AS high,
       min(price)          AS low,
       argMax(price, ts)   AS close,    -- last price in the bucket, by time
       sum(volume)         AS volume
FROM demo.ticks
GROUP BY symbol, bucket;
```

`argMin`/`argMax` pick the price at the smallest/largest `ts`, which is exactly
open and close. This is the ground truth the other two patterns reproduce from
pre-aggregated data.

## Parts do not matter here

`load.py` inserts the ticks in three separate batches, so a single bucket's
ticks are split across three parts. Because this pattern reads the raw table
directly, that split is irrelevant, because the GROUP BY sees every row. The split
becomes the point in the materialized-view patterns, where the rollup is
assembled from pre-aggregated pieces stored in those parts.

## When to choose it

Pick query-time aggregation when write cost must be zero, the bucket size is not
fixed in advance, or the raw rows per query are few. Move to a materialized-view
rollup (`materialized-view-rollups`) once queries rescan too many raw rows.

```bash
just test query-time-aggregation
```

## Reference

- [roq-trading tutorial](https://roq-trading.com/docs/tutorials/data/clickhouse/index.html)
  computes candles at query time from raw ticks, exactly this approach.
