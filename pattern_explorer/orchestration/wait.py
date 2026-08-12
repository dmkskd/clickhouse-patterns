"""Poll a query until an eventually consistent pattern converges.

Readiness ("is the container up?") is handled by compose healthchecks + --wait.
This handles the *other* kind of waiting - eventual consistency: Kafka
consumption, replication lag, merges settling - which no healthcheck can express.
"""
from __future__ import annotations

from clickhouse_connect.driver.client import Client
from tenacity import (
    retry,
    retry_if_exception_type,
    retry_if_result,
    stop_after_delay,
    wait_fixed,
)


class ConvergenceError(AssertionError):
    pass


def scalar(client: Client, query: str):
    rows = client.query(query).result_rows
    return rows[0][0] if rows else None


def wait_for(client: Client, query: str, expect, timeout: int = 60, interval: float = 1.0):
    """Poll `query` on `client` until it equals `expect`, or fail after `timeout`s."""
    last = {"value": None}

    @retry(
        stop=stop_after_delay(timeout),
        wait=wait_fixed(interval),
        # Retry both on a not-yet-matching value AND on transient errors - a
        # table that a snapshot/DDL hasn't created yet raises until it appears.
        retry=retry_if_result(lambda got: got != expect) | retry_if_exception_type(Exception),
        retry_error_callback=lambda _: last["value"],
    )
    def _poll():
        try:
            last["value"] = scalar(client, query)
        except Exception as exc:
            last["value"] = f"<error: {exc}>"
            raise
        return last["value"]

    got = _poll()
    if got != expect:
        raise ConvergenceError(
            f"{query!r} did not reach {expect!r} within {timeout}s (last: {got!r})"
        )
    return got
