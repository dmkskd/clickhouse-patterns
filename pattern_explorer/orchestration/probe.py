"""Helpers for CDC experiment scripts: write source rows at a fixed rate, then
summarise replication_latency_ms for those rows in ClickHouse.

A script picks a fresh id range, calls `insert_at_rate`, waits for the rows
with `wait_for`, and prints `result_line(...)` as its last line.
"""
from __future__ import annotations

import json
import time


def next_id(source, table: str, floor: int = 1_000_000) -> int:
    """First id above every existing row, and at least `floor`."""
    current = source.execute(f"SELECT coalesce(max(id), 0) + 1 FROM {table}").fetchone()[0]
    return max(current, floor)


def paced(first: int, rows: int, rate: int, rows_per_txn: int, write_transaction) -> float:
    """Call `write_transaction(ids)` once per transaction, at `rate` rows/s overall.

    `ids` is the slice of first..first+rows-1 for that transaction. Returns the
    elapsed seconds.
    """
    start = time.monotonic()
    for index in range(rows // rows_per_txn):
        offset = first + index * rows_per_txn
        write_transaction(range(offset, offset + rows_per_txn))
        delay = start + (index + 1) * rows_per_txn / rate - time.monotonic()
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


def result_line(result: dict) -> str:
    return "RESULT " + json.dumps(result)
