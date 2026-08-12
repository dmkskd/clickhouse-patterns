# Produce to Kafka from ClickHouse (Kafka engine write path)

Profiles: `single`, `kafka`. Driver: `ch`.

The Kafka engine works in both directions, and where the other patterns read
from it, this one writes. `INSERT INTO` a Kafka engine table produces messages
to its topic, serialized with `kafka_format`. Here ClickHouse consumes a topic, aggregates,
and produces the results to a second topic.

```
topic "events" -> events_in (Kafka) -MV-> agg (SummingMergeTree)
                                            |
                          INSERT INTO agg_out (Kafka) -> topic "aggregates"
```

`agg_out` is a Kafka engine table, so `INSERT INTO demo.agg_out SELECT …`
produces to the `aggregates` topic. That write is what the pattern demonstrates.

## Correct aggregation

A materialized view on a Kafka source fires per consumed block, so a plain
`GROUP BY` there yields per-block partials, not totals. `SummingMergeTree` fixes
that by adding `c` for rows with the same `kind` on merge, so
`sum(c) GROUP BY kind` is the correct total whether or not a background merge has
run. For non-additive aggregates (`uniqExact`, `avg`, quantiles) use
`AggregatingMergeTree` with `-State`/`-Merge` instead.

## Flow

1. Produce 8000 events to `events`.
2. `mv_agg` consumes and accumulates counts into `agg` (SummingMergeTree).
3. `load.py` waits until `sum(c) = 8000`, then
   `INSERT INTO agg_out SELECT kind, sum(c) …`, producing per-kind totals to
   `aggregates`.
4. `agg_back` reads `aggregates` back into `agg_store` so the test can assert it.

```bash
just test kafka-produce-aggregates
```

```
kind      total
click     2667
purchase  2666
view      2667
```

## Emitting on a schedule

`load.py` emits once, on demand, which keeps the test deterministic. To emit on a
schedule instead, replace the manual INSERT with a refreshable materialized view:

```sql
CREATE MATERIALIZED VIEW mv_emit REFRESH EVERY 10 SECOND APPEND TO agg_out AS
SELECT kind, sum(c) AS c FROM agg GROUP BY kind;
```

Each refresh produces a snapshot of current totals to the topic. Downstream
consumers treat the latest message per `kind` as the current value.

## Notes

- A producer Kafka table still requires `kafka_group_name`, even though it only
  writes.
- Writing to Kafka from ClickHouse is at-least-once, with no ordering guarantees
  across producers.
