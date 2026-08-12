# Refreshable materialized view (scheduled recompute from raw)

Profiles: `single`. Driver: `ch`.

Level 4 of this group. A [refreshable materialized view](https://clickhouse.com/docs/materialized-view/refreshable-materialized-view)
reruns a full query at a set interval and atomically replaces its output, rather
than maintaining it incrementally on insert. Here it revalues a trading book,
pricing the positions from the booked trades at the latest mark.

```
trade booking --> demo.trades  \
                                 REFRESH EVERY 5s --> demo.position_pnl
price feed    --> demo.prices  /
```

## Revaluation and corrections

Two things a full refresh does that an insert-triggered view cannot:

- **Revalue.** Unrealized P&L changes when the price moves, which books no trade,
  so an insert-triggered view has no insert to fire on. `load.py` moves the prices
  with no new trades, and the next refresh reflects the new P&L.
- **Dedup corrections.** The correct book is the latest version of each trade, a
  `FINAL` dedup an insert-triggered view cannot do at insert time. `load.py` amends
  and cancels a trade; the refresh reads `trades FINAL`, so the BTC position drops
  from 150 to 125.

## When to choose it

When the answer needs a full query an insert cannot express (a join to a table
that changes independently, a `FINAL` dedup, a window function), or when many
readers share one aggregation and staleness within the interval is acceptable.
Keep the query bounded to a recent window so each recompute stays cheap; the cost
is that the result lags up to the interval.

```bash
just test refreshable-materialized-views
```

## Reference

- [ClickHouse, refreshable materialized views](https://clickhouse.com/docs/materialized-view/refreshable-materialized-view)
