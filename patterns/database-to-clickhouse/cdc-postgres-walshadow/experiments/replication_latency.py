"""Insert orders into Postgres at a fixed rate and report replication latency.

Declared under spec.experiments and run against the active session by the
Explorer or `just experiment`. Each run inserts a new id range, so runs don't
overlap. Latency is replication_latency_ms (source write to ClickHouse insert)
from load.py.
"""
from __future__ import annotations

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.probe import (
    latency_summary,
    postgres_workload,
    result_line,
    insert_stage,
    stage_summary,
    workload_args,
)
from pattern_explorer.orchestration.wait import wait_for

args = workload_args()
ch = connect("ch")
first, last, started_at, elapsed = postgres_workload(ch, args)
wait_for(
    ch,
    f"SELECT count() FROM walshadow.public_orders FINAL WHERE id BETWEEN {first} AND {last}",
    args.rows,
    timeout=300,
)
result = latency_summary(ch, "walshadow", "public_orders", first, last, started_at)
result["achieved_rate"] = round(args.rows / elapsed)
result["stages"] = stage_summary(ch, "walshadow", "public_orders", first, last, [
    ("Postgres write to commit", "dateDiff('microsecond', updated_at, _commit_ts) / 1000.0"),
    ("Commit to ClickHouse insert (walshadow)", "dateDiff('microsecond', _commit_ts, ch_inserted_at) / 1000.0"),
]) + [insert_stage(result)]
print(result_line(result))
