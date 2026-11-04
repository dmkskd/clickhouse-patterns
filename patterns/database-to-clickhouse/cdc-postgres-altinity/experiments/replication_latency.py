"""Insert orders into Postgres at a fixed rate and report replication latency.

Declared under spec.experiments and run against the active session by the
Explorer or `just experiment`. Each run inserts a new id range into
public.orders, so runs don't overlap. Latency is replication_latency_ms on
test.orders (source write to ClickHouse insert), added by latency.sql.
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
ch = connect("ch-cdc")
first, last, started_at, elapsed = postgres_workload(ch, args)
wait_for(
    ch,
    f"SELECT count() FROM test.orders FINAL WHERE id BETWEEN {first} AND {last}",
    args.rows,
    timeout=300,
)
result = latency_summary(ch, "test", "orders", first, last, started_at)
result["achieved_rate"] = round(args.rows / elapsed)
# One stage: test.orders records no Postgres commit time. In 2.11 the timestamp
# in _version is the connector's effectiveTs (VersionSequencer: source time
# floored so it never goes backwards), not the commit time.
stages = stage_summary(ch, "test", "orders", first, last, [
    ("Postgres write to ClickHouse insert (Altinity connector)", "dateDiff('microsecond', updated_at, ch_inserted_at) / 1000.0"),
])
result["stages"] = split_clickhouse_insert(
    ch, "test", "orders", started_at, stages,
    "Postgres write to ClickHouse INSERT received (Altinity connector)",
)
print(result_line(result))
