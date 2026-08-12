"""Register a Debezium source and a ClickHouse sink on one Connect worker.

Both connectors run on the same Kafka Connect cluster with the topic between
them. The source unwraps Debezium's envelope before the record is published, so
the sink and any other consumer read flat rows rather than before/after pairs.
"""
from __future__ import annotations

import json
import os
import urllib.request

import psycopg

from pattern_explorer.orchestration.nodes import connect as ch_connect
from pattern_explorer.orchestration.wait import wait_for

CONNECT = os.environ.get("CONNECT_URL", "http://localhost:8083")
TOPIC = "pg.public.orders"

# Reads the WAL through pgoutput and publishes one record per change.
# ExtractNewRecordState is the SMT that flattens Debezium's envelope: it keeps
# the `after` image, rewrites a delete into the key plus __deleted, and carries
# the LSN through as __lsn for ordering. This transform is the reason the broker
# is here - it has nowhere to run in the single-process CDC patterns.
SOURCE = {
    "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
    "tasks.max": "1",
    "database.hostname": "postgres",
    "database.port": "5432",
    "database.user": "postgres",
    "database.password": "postgres",
    "database.dbname": "test",
    "topic.prefix": "pg",
    "table.include.list": "public.orders",
    "plugin.name": "pgoutput",
    "slot.name": "debezium_orders",
    "publication.autocreate.mode": "filtered",
    "tombstones.on.delete": "false",
    "key.converter": "org.apache.kafka.connect.json.JsonConverter",
    "key.converter.schemas.enable": "false",
    "value.converter": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter.schemas.enable": "false",
    "transforms": "unwrap",
    "transforms.unwrap.type": "io.debezium.transforms.ExtractNewRecordState",
    "transforms.unwrap.drop.tombstones": "true",
    "transforms.unwrap.delete.handling.mode": "rewrite",
    "transforms.unwrap.add.fields": "lsn",
}

SINK = {
    "connector.class": "com.clickhouse.kafka.connect.ClickHouseSinkConnector",
    "tasks.max": "1",
    "topics": TOPIC,
    "hostname": "ch",
    "port": "8123",
    "database": "test",
    "username": "default",
    "password": "",
    "ssl": "false",
    "exactlyOnce": "false",
    "topic2TableMap": f"{TOPIC}=orders",
    "key.converter": "org.apache.kafka.connect.json.JsonConverter",
    "key.converter.schemas.enable": "false",
    "value.converter": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter.schemas.enable": "false",
    "consumer.override.auto.offset.reset": "earliest",
    # Kafka's own coordinates, added on the sink side. topic/partition/offset
    # are only available to a sink connector, so this cannot be done upstream.
    # They make every ClickHouse row traceable to the exact record it came from.
    "transforms": "insertMeta",
    "transforms.insertMeta.type": "org.apache.kafka.connect.transforms.InsertField$Value",
    "transforms.insertMeta.topic.field": "__topic",
    "transforms.insertMeta.partition.field": "__partition",
    "transforms.insertMeta.offset.field": "__offset",
    "transforms.insertMeta.timestamp.field": "__timestamp",
}


def register(name: str, config: dict) -> None:
    request = urllib.request.Request(
        f"{CONNECT}/connectors/{name}/config",
        data=json.dumps(config).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(request) as response:
        print(f"registered {name} (HTTP {response.status})")


register("orders-source", SOURCE)
register("orders-sink", SINK)

ch = ch_connect("ch")
wait_for(ch, "SELECT count() FROM test.orders", 3, timeout=180)
print("initial snapshot reached ClickHouse through the topic (3 rows)")

with psycopg.connect(
    host="localhost",
    port=5432,
    user="postgres",
    password="postgres",
    dbname="test",
    autocommit=True,
) as source:
    source.execute(
        "INSERT INTO orders (id, customer, amount) VALUES (4, 'dave', 400) "
        "ON CONFLICT (id) DO UPDATE SET customer = EXCLUDED.customer, amount = EXCLUDED.amount"
    )
    source.execute("UPDATE orders SET amount = 250 WHERE id = 2")
    source.execute("DELETE FROM orders WHERE id = 3")
print("applied INSERT/UPDATE/DELETE to public.orders in Postgres")
