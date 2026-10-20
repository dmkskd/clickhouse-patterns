"""Await walshadow's initial load, then exercise row changes and DDL on Postgres."""
from __future__ import annotations

import psycopg

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.wait import wait_for

ch = connect("ch")
wait_for(
    ch,
    "SELECT count() FROM walshadow.public_orders FINAL",
    3,
    timeout=300,
)
print("initial load present in walshadow.public_orders (3 rows)")

with psycopg.connect(
    host="localhost",
    port=5432,
    user="postgres",
    password="postgres",
    dbname="test",
    autocommit=True,
) as source:
    source.execute("INSERT INTO orders (id, customer, amount) VALUES (4, 'dave', 400)")
    source.execute("UPDATE orders SET amount = 250 WHERE id = 2")
    source.execute("DELETE FROM orders WHERE id = 3")
    source.execute("ALTER TABLE orders ADD COLUMN status text DEFAULT 'new'")
    source.execute("UPDATE orders SET status = 'shipped' WHERE id = 4")
print("applied INSERT/UPDATE/DELETE and ADD COLUMN DEFAULT to public.orders")
