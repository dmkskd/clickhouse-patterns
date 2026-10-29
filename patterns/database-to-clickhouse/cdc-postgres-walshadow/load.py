"""Await walshadow's initial load, then exercise row changes and DDL on Postgres.

Afterwards, write timestamped probe rows so each stage of the path has its own
time on the same ClickHouse row: written_at (Postgres write), _commit_ts
(Postgres commit) and ch_inserted_at (ClickHouse insert, a DEFAULT column).
"""
from __future__ import annotations

import time

import psycopg

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.wait import wait_for

PROBE_ROWS = 200
PROBE_RATE = 50  # single-row transactions per second

ch = connect("ch")
wait_for(
    ch,
    "SELECT count() FROM walshadow.public_orders FINAL",
    3,
    timeout=300,
)
print("initial load present in walshadow.public_orders (3 rows)")

# Show the latest business write time beside the two replication timestamps.
ch.command(
    "ALTER TABLE walshadow.public_orders MODIFY COLUMN _commit_ts"
    " DateTime64(6, 'UTC') AFTER updated_at"
)


def add_latency_columns(table: str) -> None:
    """Stamp future inserts; existing rows have no measured arrival time.

    Materialize NULL before changing the default, otherwise ClickHouse could
    evaluate the new timestamp default at read time for pre-existing parts.
    The metric measures commit-to-insert time, not first query visibility;
    source and destination clocks must be synchronized.
    """
    # This pinned walshadow version uses the Postgres epoch for snapshot rows
    # whose original commit time is unavailable (including the COPY backfill).
    ch.command(
        f"ALTER TABLE walshadow.{table} ADD COLUMN replication_stage"
        " LowCardinality(String) DEFAULT if("
        "_commit_ts = toDateTime64('2000-01-01 00:00:00', 6, 'UTC'),"
        " 'Initial snapshot', 'CDC change') AFTER _commit_ts"
    )
    ch.command(
        f"ALTER TABLE walshadow.{table} ADD COLUMN ch_inserted_at"
        " Nullable(DateTime64(6, 'UTC')) DEFAULT NULL AFTER _commit_ts"
    )
    ch.command(
        f"ALTER TABLE walshadow.{table} MATERIALIZE COLUMN ch_inserted_at"
        " SETTINGS mutations_sync = 1"
    )
    ch.command(
        f"ALTER TABLE walshadow.{table} MODIFY COLUMN ch_inserted_at"
        " Nullable(DateTime64(6, 'UTC')) DEFAULT now64(6, 'UTC')"
    )
    ch.command(
        f"ALTER TABLE walshadow.{table} ADD COLUMN replication_latency_ms"
        " Nullable(Float64) DEFAULT if("
        "ch_inserted_at IS NOT NULL AND _commit_ts > toDateTime64('2000-01-01 00:00:00', 6, 'UTC'),"
        " dateDiff('microsecond', _commit_ts, ch_inserted_at) / 1000.0, NULL)"
    )


add_latency_columns("public_orders")

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

    # Keep business columns together in SELECT * and the live Contents view.
    wait_for(
        ch,
        "SELECT count() FROM system.columns WHERE database = 'walshadow'"
        " AND table = 'public_orders' AND name = 'status'",
        1,
        timeout=120,
    )
    ch.command(
        "ALTER TABLE walshadow.public_orders MODIFY COLUMN status"
        " Nullable(String) DEFAULT 'new' AFTER amount"
    )
    ch.command(
        "ALTER TABLE walshadow.public_orders"
        " MODIFY COLUMN replication_latency_ms Nullable(Float64) DEFAULT if("
        "ch_inserted_at IS NOT NULL AND _commit_ts > toDateTime64('2000-01-01 00:00:00', 6, 'UTC'),"
        " dateDiff('microsecond', _commit_ts, ch_inserted_at) / 1000.0, NULL) AFTER status,"
        " MODIFY COLUMN replication_stage LowCardinality(String) DEFAULT if("
        "_commit_ts = toDateTime64('2000-01-01 00:00:00', 6, 'UTC'),"
        " 'Initial snapshot', 'CDC change') AFTER replication_latency_ms"
    )

    # Each statement commits separately, producing another CDC row version.
    source.execute("INSERT INTO orders (id, customer, amount) VALUES (5, 'erin', 500)")
    source.execute("INSERT INTO orders (id, customer, amount) VALUES (6, 'frank', 600)")
    source.execute("INSERT INTO orders (id, customer, amount) VALUES (7, 'grace', 700)")
    source.execute("UPDATE orders SET status = 'shipped' WHERE id = 5")
    source.execute("UPDATE orders SET amount = 650 WHERE id = 6")
    source.execute("DELETE FROM orders WHERE id = 7")
    print("applied six more CDC changes: three inserts, two updates and one delete")

    # replicate_all = true: walshadow creates walshadow.public_latency_probe.
    source.execute(
        """
        CREATE TABLE latency_probe (
            id bigserial PRIMARY KEY,
            written_at timestamptz NOT NULL DEFAULT clock_timestamp()
        )
        """
    )
    wait_for(
        ch,
        "SELECT count() FROM system.tables"
        " WHERE database = 'walshadow' AND name = 'public_latency_probe'",
        1,
        timeout=120,
    )
    # walshadow names its columns on INSERT, leaving these defaults to ClickHouse.
    add_latency_columns("public_latency_probe")

    start = time.monotonic()
    for i in range(PROBE_ROWS):
        source.execute("INSERT INTO latency_probe DEFAULT VALUES")
        delay = start + (i + 1) / PROBE_RATE - time.monotonic()
        if delay > 0:
            time.sleep(delay)
    print(f"wrote {PROBE_ROWS} probe rows at {PROBE_RATE}/s to public.latency_probe")
