"""Insert orders into MySQL at a fixed rate and report replication latency.

Declared under spec.experiments and run against the active session by the
Explorer or `just experiment`. Each run inserts a new id range into test.orders,
so runs don't overlap. Latency is replication_latency_ms on the ClickHouse
test.orders (source write to ClickHouse insert), added by latency.sql.
"""
from __future__ import annotations

import pymysql

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.probe import (
    ID_FLOOR,
    latency_summary,
    paced,
    result_line,
    insert_stage,
    stage_summary,
    workload_args,
)
from pattern_explorer.orchestration.wait import wait_for

args = workload_args()
ch = connect("ch-cdc")

source = pymysql.connect(host="localhost", port=3306, user="root", password="root",
                         database="test", autocommit=False)
try:
    with source.cursor() as cursor:
        cursor.execute("SELECT coalesce(max(id), 0) + 1 FROM orders")
        first = max(cursor.fetchone()[0], ID_FLOOR)
        started_at = ch.query("SELECT now64(6, 'UTC')").result_rows[0][0]

        def write(ids):
            cursor.executemany(
                "INSERT INTO orders (id, customer, amount) VALUES (%s, 'probe', 0)",
                [(row_id,) for row_id in ids],
            )
            source.commit()

        elapsed = paced(first, args.rows, args.rate, args.rows_per_txn, write)
finally:
    source.close()
last = first + args.rows - 1

print(f"wrote ids {first}..{last} ({args.rows} rows) in {elapsed:.1f}s")
wait_for(
    ch,
    f"SELECT count() FROM test.orders FINAL WHERE id BETWEEN {first} AND {last}",
    args.rows,
    timeout=300,
)
result = latency_summary(ch, "test", "orders", first, last, started_at)
result["achieved_rate"] = round(args.rows / elapsed)
# _version is the connector's snowflake ID (2.9.1 ClickHouseStruct.calculateVersion):
# source.ts_ms, the MySQL commit time in milliseconds, in the top bits since the
# Twitter epoch (1288834974657).
commit = "fromUnixTimestamp64Milli(toInt64(bitShiftRight(_version, 22) + 1288834974657), 'UTC')"
result["stages"] = stage_summary(ch, "test", "orders", first, last, [
    ("MySQL write to commit", f"dateDiff('microsecond', updated_at, {commit}) / 1000.0"),
    ("Commit to ClickHouse insert (Altinity connector)", f"dateDiff('microsecond', {commit}, ch_inserted_at) / 1000.0"),
]) + [insert_stage(result)]
print(result_line(result))
