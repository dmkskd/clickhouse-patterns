# Cascading materialized views (rollups built from rollups)

Profiles: `single`. Driver: `ch`.

Level 3 of this group. The 1-minute view
reads the raw trades; the 5-minute view reads the 1-minute rows and combines
them. ClickHouse never rereads raw to build the 5-minute rollup.

```
loader --INSERT--> demo.trades --MV--> candles_1m --MV--> candles_5m
 (3 batches)
```

This is ClickHouse's [cascading materialized views](https://clickhouse.com/docs/guides/developer/cascading-materialized-views):
one view feeds a table that a second view reads from.

## Additive vs non-additive

When a coarser rollup is built from a finer one, two kinds of column behave
differently:

- `high`, `low`, `volume` are additive. The highest of the highs is still the
  highest; the sum of sums is the total. They use `SimpleAggregateFunction` and
  combine with ordinary `max`/`min`/`sum` at every level. These compose without
  special handling, and they are what most examples show.
- `open`, `close` are not additive. The first or last price of five minutes
  cannot be recovered from five finished numbers without the underlying state. They use a
  full `AggregateFunction`, and the 5-minute view combines the 1-minute states
  with the `-MergeState` combinator (`argMinMergeState`/`argMaxMergeState`) rather
  than the `-State` used against raw.

Getting that second case right across levels is what this pattern demonstrates.

## Spanning parts across levels

`load.py` inserts the trades in three batches, so each 1-minute row is assembled
from three pieces in three parts (as in the fan-out pattern). The cascade then
combines those 1-minute rows across three minutes into one 5-minute row:

```
raw (3 parts/min) --> candles_1m: 3 pieces per minute
                  --> candles_5m: 3 minutes combined into one 5-minute bucket
```

Both levels combine pieces, so the final 5-minute row is correct no matter how
the inserts were split. The test asserts the cascaded 5-minute row equals the
same window computed directly from raw.

## When to choose it

Cascade when several resolutions are kept and each insert should be aggregated once
per level rather than rescanned per resolution. The cost is coupling, since levels
depend on each other, rebuilds have to run in order, and a corrected raw row has
to flow through every level.

```bash
just test cascading-materialized-views
```

## Reference

- [ObsessionDB, feeding OHLC candles to TradingView from ClickHouse](https://obsessiondb.com/blog/ohlc-candles-tradingview-clickhouse)
  uses cascaded AggregatingMergeTree tables at 1m/5m/1h/1d so a chart load never
  touches a raw event.
