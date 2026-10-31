"""Insert orders into MySQL at a fixed rate and report replication latency.

Declared under spec.experiments; the Explorer runs it against the active
session. Each run inserts a new id range into test.orders, so runs don't
overlap. Latency is replication_latency_ms on the ClickHouse test.orders
(source write to ClickHouse insert), added by latency.sql.
"""
from __future__ import annotations

import argparse

import pymysql

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.probe import latency_summary, paced, result_line, stage_summary
from pattern_explorer.orchestration.wait import wait_for

parser = argparse.ArgumentParser()
parser.add_argument("--rate", type=int, default=50, help="rows per second")
parser.add_argument("--rows-per-txn", type=int, default=1)
parser.add_argument("--duration", type=int, default=10, help="seconds")
args = parser.parse_args()

ch = connect("ch-cdc")
rows = args.rate * args.duration // args.rows_per_txn * args.rows_per_txn

source = pymysql.connect(host="localhost", port=3306, user="root", password="root",
                         database="test", autocommit=False)
with source.cursor() as cursor:
    cursor.execute("SELECT coalesce(max(id), 0) + 1 FROM orders")
    first = max(cursor.fetchone()[0], 1_000_000)
    last = first + rows - 1
    started_at = ch.query("SELECT now64(6, 'UTC')").result_rows[0][0]

    def write(ids):
        cursor.executemany(
            "INSERT INTO orders (id, customer, amount) VALUES (%s, 'probe', 0)",
            [(row_id,) for row_id in ids],
        )
        source.commit()

    elapsed = paced(first, rows, args.rate, args.rows_per_txn, write)
source.close()

print(f"wrote ids {first}..{last} ({rows} rows) in {elapsed:.1f}s")
wait_for(
    ch,
    f"SELECT count() FROM test.orders FINAL WHERE id BETWEEN {first} AND {last}",
    rows,
    timeout=300,
)
result = latency_summary(ch, "test", "orders", first, last, started_at)
result["achieved_rate"] = round(rows / elapsed)
# _version is the connector's snowflake ID (2.9.1 ClickHouseStruct.calculateVersion):
# source.ts_ms, the MySQL commit time in milliseconds, in the top bits since the
# Twitter epoch (1288834974657).
commit = "fromUnixTimestamp64Milli(toInt64(bitShiftRight(_version, 22) + 1288834974657), 'UTC')"
result["stages"] = stage_summary(ch, "test", "orders", first, last, [
    ("MySQL write to commit", f"dateDiff('microsecond', updated_at, {commit}) / 1000.0"),
    ("Commit to ClickHouse insert (Altinity connector)", f"dateDiff('microsecond', {commit}, ch_inserted_at) / 1000.0"),
])
print(result_line(result))
