"""Helpers for the database CDC experiments (database-to-clickhouse cdc-*
patterns) only: write source rows at a fixed rate, then summarise
replication_latency_ms for those rows in ClickHouse.

They assume a target table with `id`, `replication_latency_ms` and
`ch_inserted_at` columns. The ClickHouse breakdown (async insert buffer, part
write) was verified on walshadow (async INSERTs) and the Altinity sink
(synchronous INSERTs) on ClickHouse 26.9.
"""
from __future__ import annotations

import argparse
import math

from pattern_explorer.orchestration.probe import paced

ID_FLOOR = 1_000_000  # probe ids start here, above the rows load.py writes


def next_id(source, table: str, floor: int = ID_FLOOR) -> int:
    """First id above every existing row, and at least `floor`."""
    current = source.execute(f"SELECT coalesce(max(id), 0) + 1 FROM {table}").fetchone()[0]
    return max(current, floor)


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
    """Latency quantiles for the id range, plus parts created in the table
    since `started_at`."""
    ch.command("SYSTEM FLUSH LOGS")
    p50, p95, p99, peak = ch.query(
        "SELECT round(quantile(0.5)(replication_latency_ms), 1),"
        " round(quantile(0.95)(replication_latency_ms), 1),"
        " round(quantile(0.99)(replication_latency_ms), 1),"
        " round(max(replication_latency_ms), 1)"
        f" FROM {database}.{table} WHERE id BETWEEN {first} AND {last}"
    ).result_rows[0]
    # New parts and the time ClickHouse took to write each one.
    parts, part_write_avg, part_write_max = ch.query(
        "SELECT count(), round(avg(duration_ms), 1), max(duration_ms) FROM system.part_log"
        " WHERE database = {database:String} AND table = {table:String}"
        " AND event_type = 'NewPart' AND event_time_microseconds >= {started_at:DateTime64(6)}",
        parameters={"database": database, "table": table, "started_at": started_at},
    ).result_rows[0]
    # Async INSERTs: how long each one's data waited in ClickHouse's buffer
    # until the flush. Synchronous INSERTs leave no entries, so both are empty.
    buffer_avg, buffer_max = ch.query(
        "SELECT if(count() = 0, NULL, round(avg(dateDiff('microsecond', event_time_microseconds, flush_time_microseconds)) / 1000.0, 1)),"
        " if(count() = 0, NULL, round(max(dateDiff('microsecond', event_time_microseconds, flush_time_microseconds)) / 1000.0, 1))"
        " FROM system.asynchronous_insert_log"
        " WHERE database = {database:String} AND table = {table:String}"
        " AND status = 'Ok' AND event_time_microseconds >= {started_at:DateTime64(6)}",
        parameters={"database": database, "table": table, "started_at": started_at},
    ).result_rows[0]
    return {
        "rows": last - first + 1,
        "p50_ms": p50,
        "p95_ms": p95,
        "p99_ms": p99,
        "max_ms": peak,
        "parts": parts,
        "async_buffer_avg_ms": buffer_avg,
        "async_buffer_max_ms": buffer_max,
        "part_write_avg_ms": part_write_avg,
        "part_write_max_ms": part_write_max,
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


def split_clickhouse_insert(
    ch, database: str, table: str, started_at, stages: list[dict], client_label: str
) -> list[dict]:
    """Add ClickHouse's part of the insert to the timeline stages.

    Async INSERTs (async_insert = 1, the server default) leave entries in
    system.asynchronous_insert_log. The last stage then splits into the client's
    part under `client_label`, the wait in ClickHouse's async insert buffer and
    the part write. The wait is flush_time minus event_time; flush_time follows
    the part write, so the write is taken out of the wait and the three still
    add up to the last stage.

    Synchronous INSERTs: the part write is appended as an `extra` segment,
    drawn but not added to the total, on the assumption that ch_inserted_at is
    set before the part write. Not measured.

    Both values are weighted by rows, so they are per-row averages like the stages.
    """
    window = {"database": database, "table": table, "started_at": started_at}
    part_write = ch.query(
        "SELECT round(sum(rows * duration_ms) / sum(rows), 1) FROM system.part_log"
        " WHERE database = {database:String} AND table = {table:String}"
        " AND event_type = 'NewPart' AND event_time_microseconds >= {started_at:DateTime64(6)}",
        parameters=window,
    ).result_rows[0][0]
    wait = ch.query(
        "SELECT round(sum(rows * dateDiff('microsecond', event_time_microseconds,"
        " flush_time_microseconds)) / sum(rows) / 1000.0, 1)"
        " FROM system.asynchronous_insert_log"
        " WHERE database = {database:String} AND table = {table:String}"
        " AND status = 'Ok' AND event_time_microseconds >= {started_at:DateTime64(6)}",
        parameters=window,
    ).result_rows[0][0]
    finite = lambda value: value is not None and math.isfinite(value)
    if not finite(part_write) or stages[-1]["ms"] is None:
        return stages
    if not finite(wait):
        return stages + [{"label": "ClickHouse part write", "ms": part_write, "extra": True}]
    return stages[:-1] + [
        {"label": client_label, "ms": round(stages[-1]["ms"] - wait, 1)},
        {"label": "ClickHouse async insert buffer", "ms": round(wait - part_write, 1)},
        {"label": "ClickHouse part write", "ms": part_write},
    ]
