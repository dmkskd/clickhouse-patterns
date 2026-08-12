"""Create a PeerDB mirror, await its snapshot, then exercise Postgres CDC."""
from __future__ import annotations

import time
from pathlib import Path

import psycopg

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.sql import run_sql_file
from pattern_explorer.orchestration.wait import wait_for


def connect_peerdb(timeout: int = 120):
    """Wait for PeerDB's Postgres-compatible SQL endpoint to accept commands."""
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            return psycopg.connect(
                host="localhost",
                port=9900,
                user="peerdb",
                password="peerdb",
                dbname="peerdb",
                autocommit=True,
                connect_timeout=3,
            )
        except psycopg.OperationalError as exc:
            last_error = exc
            time.sleep(2)
    raise TimeoutError("PeerDB SQL endpoint did not become ready") from last_error


with connect_peerdb() as peerdb:
    peerdb.execute(
        """
        CREATE PEER IF NOT EXISTS postgres_source FROM POSTGRES WITH (
            host = 'postgres',
            port = '5432',
            user = 'postgres',
            password = 'postgres',
            database = 'test'
        )
        """
    )
    peerdb.execute(
        """
        CREATE PEER IF NOT EXISTS clickhouse_target FROM CLICKHOUSE WITH (
            host = 'ch',
            port = '9000',
            user = 'default',
            password = '',
            database = 'test',
            s3_path = 's3://clickhouse/peerdb',
            access_key_id = 'clickhouse',
            secret_access_key = 'clickhouse_secret',
            region = 'us-east-1',
            disable_tls = true,
            endpoint = 'http://minio:9000'
        )
        """
    )
    peerdb.execute(
        """
        CREATE MIRROR IF NOT EXISTS two_table_mirror
        FROM postgres_source TO clickhouse_target
        WITH TABLE MAPPING (
            public.orders:orders,
            public.orders_existing:orders_existing
        )
        WITH (
            do_initial_copy = true,
            sync_interval = 1
        )
        """
    )
print("created PeerDB source, target, and two-table orders mirror")

ch = connect("ch")
wait_for(
    ch,
    "SELECT count() FROM test.orders FINAL WHERE _peerdb_is_deleted = 0",
    3,
    timeout=180,
)
wait_for(
    ch,
    "SELECT count() FROM test.orders_existing FINAL WHERE _peerdb_is_deleted = 0",
    3,
    timeout=180,
)
print("initial snapshots present in PeerDB-created and existing targets (3 rows each)")

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
    for table in ("orders", "orders_existing"):
        source.execute(f"INSERT INTO {table} (id, customer, amount) VALUES (4, 'dave', 400)")
        source.execute(f"UPDATE {table} SET amount = 250 WHERE id = 2")
        source.execute(f"DELETE FROM {table} WHERE id = 3")
print("applied matching INSERT/UPDATE/DELETE operations to both Postgres source tables")
