"""Register the ClickHouse Sink connector via the Connect REST API, then produce.

This is the "push" half: instead of CH pulling via a Kafka engine table, an
external Kafka Connect worker consumes the topic and writes to CH over HTTP.
"""
import json
import os
import time
import urllib.request

from pattern_explorer.orchestration.kafka_load import produce_partitioned

CONNECT = os.environ.get("CONNECT_URL", "http://localhost:8083")

CONNECTOR = {
    "connector.class": "com.clickhouse.kafka.connect.ClickHouseSinkConnector",
    "tasks.max": "1",
    "topics": "events",
    "hostname": "ch",            # reachable on the compose network
    "port": "8123",              # ClickHouse HTTP
    "database": "demo",          # topic 'events' -> table demo.events
    "username": "default",
    "password": "",
    "ssl": "false",
    "exactlyOnce": "false",      # at-least-once; see README for exactly-once
    "key.converter": "org.apache.kafka.connect.storage.StringConverter",
    "value.converter": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter.schemas.enable": "false",
    "consumer.override.auto.offset.reset": "earliest",
}


def register():
    req = urllib.request.Request(
        f"{CONNECT}/connectors/clickhouse-sink/config",
        data=json.dumps(CONNECTOR).encode(),
        headers={"Content-Type": "application/json"},
        method="PUT",
    )
    with urllib.request.urlopen(req) as resp:
        print(f"connector registered (HTTP {resp.status})")


register()
time.sleep(3)                    # let the task start & subscribe
produce_partitioned("events", n=8000, partitions=1)
