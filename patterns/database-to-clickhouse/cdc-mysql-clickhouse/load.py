"""Prepare the transformation, then exercise all three CDC table paths."""
from pathlib import Path

import pymysql

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.sql import run_sql_file
from pattern_explorer.orchestration.wait import wait_for

ch = connect("ch-cdc")
wait_for(ch, "SELECT count() FROM test.orders FINAL WHERE is_deleted = 0", 3, timeout=120)
wait_for(
    ch,
    "SELECT count() FROM test.orders_existing FINAL WHERE is_deleted = 0",
    3,
    timeout=120,
)
print("initial snapshots present in CDC-created and existing targets (3 rows each)")

run_sql_file(ch, Path(__file__).with_name("transform.sql"))
print("created and backfilled the materialized-view transformation")

conn = pymysql.connect(host="localhost", port=3306, user="root", password="root",
                       database="test", autocommit=True)
with conn.cursor() as cur:
    # One mutation of each kind, so verify.sql can prove propagation end to end.
    # The update crosses the amount_band threshold (200 -> 250 >= 250), making it
    # visible in the transformed table's computed column, not just in the amount.
    for table in ("orders", "orders_existing"):
        cur.execute(f"INSERT INTO {table} (id, customer, amount) VALUES (4, 'dave', 400)")
        cur.execute(f"UPDATE {table} SET amount = 250 WHERE id = 2")
        cur.execute(f"DELETE FROM {table} WHERE id = 3")
conn.close()
print("applied matching INSERT/UPDATE/DELETE operations to both MySQL source tables")
