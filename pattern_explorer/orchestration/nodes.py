"""Connect to ClickHouse nodes exposed by the local orchestration stack."""
from __future__ import annotations

import clickhouse_connect
from clickhouse_connect.driver.client import Client

# node name -> published HTTP port on localhost (see compose/stack.yml).
# Ports are reused across profiles because only one profile runs at a time.
NODE_HTTP_PORT = {
    "ch": 8123,     # single profile
    "ch-01": 8123,  # cluster profile
    "ch-02": 8124,  # cluster profile
    "ch-s1": 8123,  # shards profile
    "ch-s2": 8124,  # shards profile
    "ch-s1v2": 8123,  # shards-v2 profile (ClickHouse head, StorageKafka2)
    "ch-s2v2": 8124,  # shards-v2 profile (ClickHouse head, StorageKafka2)
    "ch-s3q": 8123,   # s3queue profile (single node + Keeper, for S3Queue)
    "ch-cdc": 8123, # cdc-ch profile (pinned ClickHouse for CDC)
}

# Reachable from inside the compose network (e.g. for BACKUP/RESTORE endpoints).
KAFKA_INTERNAL_BOOTSTRAP = "kafka:9094"
KAFKA_HOST_BOOTSTRAP = "localhost:9092"


def connect(node: str) -> Client:
    if node not in NODE_HTTP_PORT:
        raise KeyError(f"unknown node {node!r}; known: {sorted(NODE_HTTP_PORT)}")
    return clickhouse_connect.get_client(
        host="localhost",
        port=NODE_HTTP_PORT[node],
        username="default",
        password="",
    )
