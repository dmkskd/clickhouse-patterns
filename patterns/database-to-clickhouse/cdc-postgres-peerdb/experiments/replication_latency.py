"""Insert orders into Postgres at a fixed rate and report replication latency.

Declared under spec.experiments and run against the active session by the
Explorer or `just experiment`. Each run inserts a new id range into
public.orders, so runs don't overlap. Latency is replication_latency_ms on
test.orders (source write to ClickHouse insert), added by latency.sql.
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
    f"SELECT count() FROM test.orders FINAL WHERE id BETWEEN {first} AND {last}",
    args.rows,
    timeout=300,
)
result = latency_summary(ch, "test", "orders", first, last, started_at)
result["achieved_rate"] = round(args.rows / elapsed)
# _peerdb_version is the raw record's _peerdb_timestamp: the time PeerDB read
# the change from the replication stream (nanoseconds; flow/connectors/utils/
# stream.go at v0.37.0). PeerDB records no time for the raw-table insert, so
# batching, staging and normalize are one stage.
read = "fromUnixTimestamp64Nano(toInt64(_peerdb_version), 'UTC')"
result["stages"] = stage_summary(ch, "test", "orders", first, last, [
    ("Postgres write to PeerDB read", f"dateDiff('microsecond', updated_at, {read}) / 1000.0"),
    ("PeerDB read to ClickHouse insert (batch, raw table, normalize)", f"dateDiff('microsecond', {read}, ch_inserted_at) / 1000.0"),
]) + [insert_stage(result)]
print(result_line(result))
