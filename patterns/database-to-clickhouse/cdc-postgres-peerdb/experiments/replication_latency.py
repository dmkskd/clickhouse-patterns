"""Insert orders into Postgres at a fixed rate and report replication latency.

Declared under spec.experiments; the Explorer runs it against the active
session. Each run inserts a new id range into public.orders, so runs don't
overlap. Latency is replication_latency_ms on test.orders (source write to
ClickHouse insert), added by latency.sql.
"""
from __future__ import annotations

import argparse

import psycopg

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.probe import (
    insert_at_rate,
    latency_summary,
    next_id,
    result_line,
    stage_summary,
)
from pattern_explorer.orchestration.wait import wait_for

parser = argparse.ArgumentParser()
parser.add_argument("--rate", type=int, default=50, help="rows per second")
parser.add_argument("--rows-per-txn", type=int, default=1)
parser.add_argument("--duration", type=int, default=10, help="seconds")
args = parser.parse_args()

ch = connect("ch")
rows = args.rate * args.duration // args.rows_per_txn * args.rows_per_txn

with psycopg.connect(
    host="localhost",
    port=5432,
    user="postgres",
    password="postgres",
    dbname="test",
    autocommit=True,
) as source:
    first = next_id(source, "orders")
    last = first + rows - 1
    started_at = ch.query("SELECT now64(6, 'UTC')").result_rows[0][0]
    elapsed = insert_at_rate(source, "orders", first, rows, args.rate, args.rows_per_txn)

print(f"wrote ids {first}..{last} ({rows} rows) in {elapsed:.1f}s")
wait_for(
    ch,
    f"SELECT count() FROM test.orders FINAL WHERE id BETWEEN {first} AND {last}",
    rows,
    timeout=300,
)
result = latency_summary(ch, "test", "orders", first, last, started_at)
# _peerdb_version is the raw record's _peerdb_timestamp: the time PeerDB read
# the change from the replication stream (nanoseconds). PeerDB records no time
# for the raw-table insert, so batching, staging and normalize are one stage.
read = "fromUnixTimestamp64Nano(toInt64(_peerdb_version), 'UTC')"
result["stages"] = stage_summary(ch, "test", "orders", first, last, [
    ("Postgres write to PeerDB read", f"dateDiff('microsecond', updated_at, {read}) / 1000.0"),
    ("PeerDB read to ClickHouse insert (batch, raw table, normalize)", f"dateDiff('microsecond', {read}, ch_inserted_at) / 1000.0"),
])
print(result_line(result))
