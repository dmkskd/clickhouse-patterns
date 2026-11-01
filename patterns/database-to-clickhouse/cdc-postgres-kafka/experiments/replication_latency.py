"""Insert orders into Postgres at a fixed rate and report replication latency.

Declared under spec.experiments and run against the active session by the
Explorer or `just experiment`. Each run inserts a new id range into
public.orders, so runs don't overlap. Latency is replication_latency_ms on
test.orders (source write to ClickHouse insert, through Debezium, Kafka and the
ClickHouse sink), added by latency.sql.
"""
from __future__ import annotations

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.pattern_specific.cdc_latency import (
    latency_summary,
    postgres_workload,
    split_clickhouse_insert,
    stage_summary,
)
from pattern_explorer.orchestration.probe import result_line, workload_args
from pattern_explorer.orchestration.wait import wait_for

args = workload_args()
ch = connect("ch")
first, last, started_at, elapsed = postgres_workload(ch, args)
wait_for(
    ch,
    f"SELECT count() FROM test.orders FINAL WHERE id BETWEEN {first} AND {last}",
    args.rows,
    timeout=300,
)
result = latency_summary(ch, "test", "orders", first, last, started_at)
result["achieved_rate"] = round(args.rows / elapsed)
# __source_ts_ms: Debezium source.ts_ms (Postgres commit time, millisecond
# precision). __timestamp: Kafka record timestamp, the producer's CreateTime
# when Connect sent the record (runs show a positive commit-to-Kafka stage).
commit = "fromUnixTimestamp64Milli(assumeNotNull(__source_ts_ms), 'UTC')"
stages = stage_summary(ch, "test", "orders", first, last, [
    ("Postgres write to commit", f"dateDiff('microsecond', updated_at, {commit}) / 1000.0"),
    ("Commit to Kafka (Debezium)", f"dateDiff('microsecond', {commit}, __timestamp) / 1000.0"),
    ("Kafka to ClickHouse insert (sink)", "dateDiff('microsecond', __timestamp, ch_inserted_at) / 1000.0"),
])
result["stages"] = split_clickhouse_insert(
    ch, "test", "orders", started_at, stages,
    "Kafka to ClickHouse INSERT received (sink)",
)
print(result_line(result))
