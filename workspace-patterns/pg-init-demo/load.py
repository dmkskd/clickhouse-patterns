"""Change Postgres, then read it back through ClickHouse with nothing in between.

There is no pipeline to wait for. The INSERT/UPDATE/DELETE below are visible to
ClickHouse on the next SELECT, because ClickHouse holds no copy of the data.
"""
from __future__ import annotations

import psycopg

from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")
before = ch.query("SELECT count() FROM test.orders_table_engine").result_rows[0][0]
print(f"read {before} rows straight out of Postgres through test.orders_table_engine")

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

after = ch.query("SELECT count() FROM test.orders_table_engine").result_rows[0][0]
print(f"the next ClickHouse read already returns {after} rows, with no lag")
