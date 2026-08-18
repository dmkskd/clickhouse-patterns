# Materialized view rollups (fan-out from raw)

Profiles: `single`. Driver: `ch`.

Level 2 of this group. Each time bucket is a materialized view attached to the
raw table as a trigger: it runs its query on each newly inserted block and
writes a pre-aggregated row into an `AggregatingMergeTree`. Queries read
the small pre-aggregated table instead of the raw stream.

```
                        +--MV (per insert)--> candles_1m (AggregatingMergeTree)
loader --INSERT-->  demo.ticks
 (3 batches)            +--MV (per insert)--> candles_5m (AggregatingMergeTree)
```

Both views trigger on inserts into raw `demo.ticks`, which is what fan-out means
here. The 5-minute rollup does not reuse the 1-minute one; each inserted block
goes to both views independently. (Building 5m from the 1m rows is the next
pattern, `cascading-materialized-views`.)

## Two kinds of column

Not every column needs the same machinery:

- `high`, `low`, `volume` are additive, so they use `SimpleAggregateFunction`,
  which stores a finished, readable number. `SELECT * FROM candles_1m` shows them as
  ordinary values, and they are read back with `max`/`min`/`sum`.
- `open`, `close` need `argMin`/`argMax`, which cannot be reduced to one running
  number, so they use a full `AggregateFunction` written with
  `argMinState`/`argMaxState` and read back with `argMinMerge`/`argMaxMerge`. In a
  raw `SELECT *` those two columns look like opaque binary, which is expected.

## Spanning parts across inserts

`load.py` inserts the ticks in three separate batches. A materialized view runs
once per inserted block, so each batch writes its own pre-aggregated row into a
new part. A single bucket is therefore assembled from three pieces in three
parts:

```
insert A: open  print --MV--> candles_1m part 1  (piece for 12:00)
insert B: mid   print --MV--> candles_1m part 2  (piece for 12:00)
insert C: close print --MV--> candles_1m part 3  (piece for 12:00)
```

`AggregatingMergeTree` combines those pieces, on a background merge or on read,
so the result is correct no matter how the inserts were split. The test asserts
the combined rows equal the query-time ground truth exactly.

To watch the pieces before they merge:

```sql
SYSTEM STOP MERGES demo.candles_1m;   -- then run load, then:
SELECT bucket, count() AS pieces FROM demo.candles_1m GROUP BY bucket;
```

## When to choose it

Fan-out is simple and resilient because the time buckets are independent. The
trade-off is that every insert triggers every view, so a deep set of time buckets
makes many passes over the same rows. When that write cost hurts, cascade
instead.

```bash
just test materialized-view-rollups
```

## Reference

- [Benjamin Wootton, Real-time OHLC candlestick charts with ClickHouse](https://benjaminwootton.com/insights/ohlc-candlestick-charts-clickhouse)
  builds seven time buckets, each a view triggered by raw inserts, which is fan-out at scale.
