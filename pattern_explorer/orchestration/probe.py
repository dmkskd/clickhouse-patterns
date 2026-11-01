"""Helpers for CDC experiment scripts: write source rows at a fixed rate, then
summarise replication_latency_ms for those rows in ClickHouse.

A script parses its workload arguments with `workload_args()`, writes a fresh
id range at the requested rate (`postgres_workload`, or `paced` with its own
writer), waits for the rows with `wait_for`, and prints `result_line(...)` as
its last line. The experiments runner reads that line.
"""
from __future__ import annotations

import argparse
import json
import math
import time

RESULT_PREFIX = "RESULT "
ID_FLOOR = 1_000_000  # probe ids start here, above the rows load.py writes


def workload_args() -> argparse.Namespace:
    """The workload parameters every CDC experiment declares, with the row count."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--rate", type=int, default=50, help="rows per second")
    parser.add_argument("--rows-per-txn", type=int, default=1)
    parser.add_argument("--duration", type=int, default=10, help="seconds")
    args = parser.parse_args()
    # Whole transactions only, so the last id is exact.
    args.rows = args.rate * args.duration // args.rows_per_txn * args.rows_per_txn
    if args.rows == 0:
        parser.error("rate x duration must be at least rows-per-txn")
    return args


def next_id(source, table: str, floor: int = ID_FLOOR) -> int:
    """First id above every existing row, and at least `floor`."""
    current = source.execute(f"SELECT coalesce(max(id), 0) + 1 FROM {table}").fetchone()[0]
    return max(current, floor)


def paced(first: int, rows: int, rate: int, rows_per_txn: int, write_transaction) -> float:
    """Call `write_transaction(ids)` once per transaction, at `rate` rows/s overall.

    `ids` is the slice of first..first+rows-1 for that transaction. Returns the
    elapsed seconds.
    """
    start = time.monotonic()
    reported = start
    for index in range(rows // rows_per_txn):
        offset = first + index * rows_per_txn
        write_transaction(range(offset, offset + rows_per_txn))
        now = time.monotonic()
        written = (index + 1) * rows_per_txn
        if now - reported >= 2:
            # Progress, so a rate the source cannot sustain shows early.
            print(f"wrote {written}/{rows} rows, {written / (now - start):.0f} rows/s (requested {rate})")
            reported = now
        delay = start + written / rate - now
        if delay > 0:
            time.sleep(delay)
    return time.monotonic() - start


def insert_at_rate(source, table: str, first: int, rows: int, rate: int, rows_per_txn: int) -> float:
    """Postgres (psycopg, autocommit): insert probe orders at a fixed rate."""
    def write(ids):
        with source.transaction():
            for row_id in ids:
                source.execute(
                    f"INSERT INTO {table} (id, customer, amount) VALUES (%s, 'probe', 0)",
                    (row_id,),
                )

    return paced(first, rows, rate, rows_per_txn, write)


def postgres_workload(ch, args: argparse.Namespace, table: str = "orders") -> tuple[int, int, object, float]:
    """Write `args.rows` probe orders to the lab Postgres; return (first, last, started_at, elapsed).

    `started_at` comes from ClickHouse, so system-log filters use its clock.
    """
    import psycopg  # only Postgres-sourced patterns need the driver

    with psycopg.connect(
        host="localhost", port=5432, user="postgres", password="postgres",
        dbname="test", autocommit=True,
    ) as source:
        first = next_id(source, table)
        started_at = ch.query("SELECT now64(6, 'UTC')").result_rows[0][0]
        elapsed = insert_at_rate(source, table, first, args.rows, args.rate, args.rows_per_txn)
    last = first + args.rows - 1
    print(f"wrote ids {first}..{last} ({args.rows} rows) in {elapsed:.1f}s")
    return first, last, started_at, elapsed


def latency_summary(ch, database: str, table: str, first: int, last: int, started_at) -> dict:
    """Latency quantiles for the id range, plus parts created and INSERT
    statements run against the table since `started_at`."""
    ch.command("SYSTEM FLUSH LOGS")
    p50, p95, p99, peak = ch.query(
        "SELECT round(quantile(0.5)(replication_latency_ms), 1),"
        " round(quantile(0.95)(replication_latency_ms), 1),"
        " round(quantile(0.99)(replication_latency_ms), 1),"
        " round(max(replication_latency_ms), 1)"
        f" FROM {database}.{table} WHERE id BETWEEN {first} AND {last}"
    ).result_rows[0]
    parts = ch.query(
        "SELECT count() FROM system.part_log"
        " WHERE database = {database:String} AND table = {table:String}"
        " AND event_type = 'NewPart' AND event_time_microseconds >= {started_at:DateTime64(6)}",
        parameters={"database": database, "table": table, "started_at": started_at},
    ).result_rows[0][0]
    # INSERT statements into the table during the run: how many, and how long
    # ClickHouse took to execute them.
    inserts, insert_avg, insert_max = ch.query(
        "SELECT count(), round(avg(query_duration_ms), 1), max(query_duration_ms)"
        " FROM system.query_log"
        " WHERE type = 'QueryFinish' AND query_kind = 'Insert'"
        " AND has(tables, {qualified:String})"
        " AND event_time_microseconds >= {started_at:DateTime64(6)}",
        parameters={"qualified": f"{database}.{table}", "started_at": started_at},
    ).result_rows[0]
    return {
        "rows": last - first + 1,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "max_ms": peak,
        "parts": parts,
        "inserts": inserts,
        "insert_avg_ms": insert_avg,
        "insert_max_ms": insert_max,
    }


def stage_summary(
    ch, database: str, table: str, first: int, last: int, stages: list[tuple[str, str]]
) -> list[dict]:
    """Average milliseconds per stage, for (label, SQL expression in ms) pairs.

    Averages, not medians, so the stages add up to the average latency when
    they cover the whole path.
    """
    columns = ", ".join(f"round(avg({expression}), 1)" for _, expression in stages)
    values = ch.query(
        f"SELECT {columns} FROM {database}.{table} WHERE id BETWEEN {first} AND {last}"
        " AND replication_latency_ms IS NOT NULL"
    ).result_rows[0]
    return [{"label": label, "ms": value} for (label, _), value in zip(stages, values)]


def insert_stage(result: dict) -> dict:
    """The average ClickHouse INSERT execution as an `extra` timeline segment:
    per statement, so it is shown after the row stages but not added to them."""
    return {
        "label": "ClickHouse INSERT execution (avg per statement)",
        "ms": result.get("insert_avg_ms"),
        "extra": True,
    }


def _finite(value):
    """NaN from an empty aggregate becomes null: browsers cannot parse NaN in JSON."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _finite(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_finite(item) for item in value]
    return value


def result_line(result: dict) -> str:
    return RESULT_PREFIX + json.dumps(_finite(result))
