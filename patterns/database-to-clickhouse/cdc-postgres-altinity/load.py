"""Prepare the transformation, then exercise all three CDC table paths."""
from pathlib import Path

import psycopg

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

run_sql_file(ch, Path(__file__).with_name("latency.sql"))
run_sql_file(ch, Path(__file__).with_name("transform.sql"))
print("created and backfilled the materialized-view transformation")

with psycopg.connect(
    host="localhost",
    port=5432,
    user="postgres",
    password="postgres",
    dbname="test",
    autocommit=True,
) as source:
    # Same changes as the PeerDB pattern, so verify.sql output matches.
    for table in ("orders", "orders_existing"):
        source.execute(f"INSERT INTO {table} (id, customer, amount) VALUES (4, 'dave', 400)")
        source.execute(f"UPDATE {table} SET amount = 250 WHERE id = 2")
        source.execute(f"DELETE FROM {table} WHERE id = 3")
        source.execute(f"INSERT INTO {table} (id, customer, amount) VALUES (5, 'erin', 500)")
        source.execute(f"INSERT INTO {table} (id, customer, amount) VALUES (6, 'frank', 600)")
        source.execute(f"INSERT INTO {table} (id, customer, amount) VALUES (7, 'grace', 700)")
        source.execute(f"UPDATE {table} SET amount = 550 WHERE id = 5")
        source.execute(f"UPDATE {table} SET amount = 650 WHERE id = 6")
        source.execute(f"DELETE FROM {table} WHERE id = 7")

print("applied matching INSERT/UPDATE/DELETE operations to both Postgres source tables")
