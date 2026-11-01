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
# PeerDB's two ClickHouse statements per batch, averaged over the run: the raw
# table load from S3, and normalize into test.orders (which also runs the
# test.orders_transformed materialized view).
raw_load, normalize = ch.query(
    "SELECT"
    " round(avgIf(dateDiff('microsecond', query_start_time_microseconds, event_time_microseconds),"
    "  has(tables, '_table_function.s3')) / 1000.0, 1),"
    " round(avgIf(dateDiff('microsecond', query_start_time_microseconds, event_time_microseconds),"
    "  has(tables, 'test.orders')) / 1000.0, 1)"
    " FROM system.query_log"
    " WHERE type = 'QueryFinish' AND query_kind = 'Insert'"
    " AND has(tables, 'test._peerdb_raw_two_table_mirror')"
    " AND event_time_microseconds >= {started_at:DateTime64(6)}",
    parameters={"started_at": started_at},
).result_rows[0]
result["raw_load_ms"] = raw_load
result["normalize_ms"] = normalize
# _peerdb_version is the raw record's _peerdb_timestamp: the time PeerDB read
# the change from the replication stream (nanoseconds; flow/connectors/utils/
# stream.go at v0.37.0). PeerDB records no time for the raw-table insert, so
# batching, staging and normalize are one stage.
read = "fromUnixTimestamp64Nano(toInt64(_peerdb_version), 'UTC')"
stages = stage_summary(ch, "test", "orders", first, last, [
    ("Postgres write to PeerDB read", f"dateDiff('microsecond', updated_at, {read}) / 1000.0"),
    ("PeerDB read to ClickHouse insert (batch, raw table, normalize)", f"dateDiff('microsecond', {read}, ch_inserted_at) / 1000.0"),
])
result["stages"] = split_clickhouse_insert(
    ch, "test", "orders", started_at, stages,
    "PeerDB read to ClickHouse INSERT received (batch, raw table, normalize)",
)
print(result_line(result))
