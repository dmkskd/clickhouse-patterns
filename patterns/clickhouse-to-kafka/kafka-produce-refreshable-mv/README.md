# Refreshable MV producing to Kafka on a timer

Profiles: `single`, `kafka`. Driver: `ch`.

Streaming alerting inside ClickHouse, no external stream processor. Latency
samples arrive on a Kafka topic, ClickHouse keeps the rolling window as state,
and a refreshable materialized view produces an alert to Kafka when a service's
p90 exceeds 1000ms.

```
topic "latency" -> latency_in -> latency_raw   (rolling window, the state)
                                     |
              every 5s: mv_alerts computes p90, HAVING p90 > 1000
                                     |
                              alerts_out -> topic "alerts"
```

This is a level-only alert, so it produces while a service is breaching. For the
full firing/resolved model with hysteresis, see the sibling
[kafka-produce-refreshable-mv-transitions](../kafka-produce-refreshable-mv-transitions/).

## Producing the message

`mv_alerts` runs `INSERT INTO alerts_out SELECT …`, and inserting into a Kafka
engine table produces to the topic. A refreshable MV runs that on a timer, so
ClickHouse initiates both the read and the write with no external process.

## Refreshable MV notes

- Use `APPEND`. A refreshable MV replaces its target by default, which cannot work
  on a Kafka engine table. `APPEND` inserts each refresh, which is what produces.
- `REFRESH EVERY 5 SECOND` is the alert-latency floor. Refreshes do not overlap;
  if the query runs longer than the interval, the next one waits. Keep it cheap
  (bounded time window). Production statistical alerts are often 15 to 30s.
- May require `allow_experimental_refreshable_materialized_view=1` (set in the
  default profile here).
- Watch it with `system.view_refreshes`.

## Test

```bash
just test kafka-produce-refreshable-mv
```

`checkout` gets high latencies (p90 above 1000, alert), `health` low (no alert).
The verify asserts only `checkout` is in an alert state.
