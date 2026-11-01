"""Register a Debezium source and a ClickHouse sink on one Connect worker.

Both connectors run on the same Kafka Connect cluster with the topic between
them. The source unwraps Debezium's envelope before the record is published, so
the sink and any other consumer read flat rows rather than before/after pairs.
Edit config/source.json and config/sink.json, then run just reload to apply changes.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import urllib.request

import psycopg

from pattern_explorer.orchestration.config_overlay import config_file
from pattern_explorer.orchestration.nodes import connect as ch_connect
from pattern_explorer.orchestration.sql import run_sql_file
from pattern_explorer.orchestration.wait import wait_for

CONNECT = os.environ.get("CONNECT_URL", "http://localhost:8083")
# An experiment's edited copy, when one is active, replaces the file.
SOURCE = json.loads(config_file(Path(__file__).parent, "config/source.json").read_text())
SINK = json.loads(config_file(Path(__file__).parent, "config/sink.json").read_text())


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
run_sql_file(ch, Path(__file__).with_name("latency.sql"))

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
    source.execute("INSERT INTO orders (id, customer, amount) VALUES (5, 'erin', 500)")
    source.execute("INSERT INTO orders (id, customer, amount) VALUES (6, 'frank', 600)")
    source.execute("INSERT INTO orders (id, customer, amount) VALUES (7, 'grace', 700)")
    source.execute("UPDATE orders SET amount = 550 WHERE id = 5")
    source.execute("UPDATE orders SET amount = 650 WHERE id = 6")
    source.execute("DELETE FROM orders WHERE id = 7")

print("applied INSERT/UPDATE/DELETE to public.orders in Postgres")
