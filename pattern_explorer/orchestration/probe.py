"""Helpers common to every experiment script: workload arguments, a fixed-rate
writer loop, and the RESULT line the experiments runner reads.

A script parses its workload arguments with `workload_args()`, writes at the
requested rate with `paced`, and prints `result_line(...)` as its last line.
Helpers for one pattern family are in `pattern_specific/`.
"""
from __future__ import annotations

import argparse
import json
import math
import time

RESULT_PREFIX = "RESULT "


def workload_args() -> argparse.Namespace:
    """Rate, rows per transaction and duration, with the resulting row count."""
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
