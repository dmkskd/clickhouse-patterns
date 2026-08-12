"""Change Postgres, observe the staleness window, then wait for one refresh.

Between the two reads the Postgres row is already gone while the ClickHouse copy
still shows it. That gap is the staleness this pattern trades for its simplicity.
"""
from __future__ import annotations

import psycopg

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.wait import wait_for

ch = connect("ch")
wait_for(ch, "SELECT count() FROM test.orders", 3, timeout=90)
print("initial refresh landed 3 rows in the local MergeTree")

# The append-only history must observe the pre-change state before anything is
# mutated, otherwise its first snapshot lands after the delete and the row this
# pattern is about never enters the history at all.
wait_for(ch, "SELECT count() FROM test.orders_history WHERE id = 3", 1, timeout=90)
print("history captured its first snapshot, with id 3 still present")

with psycopg.connect(
    host="localhost",
    port=5432,
    user="postgres",
    password="postgres",
    dbname="test",
    autocommit=True,
) as source:
    # Idempotent so the load survives a source container that outlived a
    # previous run; a plain INSERT fails on the primary key.
    source.execute(
        "INSERT INTO orders (id, customer, amount) VALUES (4, 'dave', 400) "
        "ON CONFLICT (id) DO UPDATE SET customer = EXCLUDED.customer, amount = EXCLUDED.amount"
    )
    source.execute("UPDATE orders SET amount = 250 WHERE id = 2")
    source.execute("DELETE FROM orders WHERE id = 3")
print("applied INSERT/UPDATE/DELETE to public.orders in Postgres")

live = ch.query("SELECT count() FROM test.pg_orders").result_rows[0][0]
copy = ch.query("SELECT count() FROM test.orders").result_rows[0][0]
print(f"pass-through read sees {live} rows; the refreshed copy still sees {copy}")
print("waiting for the next scheduled refresh")
