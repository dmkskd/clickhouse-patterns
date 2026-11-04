"""Insert orders into MySQL at a fixed rate and report replication latency.

Declared under spec.experiments and run against the active session by the
Explorer or `just experiment`. Each run inserts a new id range into test.orders,
so runs don't overlap. Latency is replication_latency_ms on the ClickHouse
test.orders (source write to ClickHouse insert), added by latency.sql.
"""
from __future__ import annotations

import pymysql

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.pattern_specific.cdc_latency import (
    ID_FLOOR,
    latency_summary,
    split_clickhouse_insert,
    stage_summary,
)
from pattern_explorer.orchestration.probe import paced, result_line, workload_args
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
# One stage: test.orders records no MySQL commit time. In 2.11 the timestamp in
# _version is the connector's effectiveTs (VersionSequencer: source time floored
# so it never goes backwards), not the commit time; decoded, it fell after
# ch_inserted_at for some rows.
stages = stage_summary(ch, "test", "orders", first, last, [
    ("MySQL write to ClickHouse insert (Altinity connector)", "dateDiff('microsecond', updated_at, ch_inserted_at) / 1000.0"),
])
result["stages"] = split_clickhouse_insert(
    ch, "test", "orders", started_at, stages,
    "MySQL write to ClickHouse INSERT received (Altinity connector)",
)
print(result_line(result))
