"""Exactly-once proof for the push connector.

  1. register the sink with exactlyOnce=true and ingest 8000 rows
  2. STOP the connector, DELETE its committed offsets, RESUME it
     -> the connector re-reads all 8000 records from offset 0
  3. exactly-once: the KeeperMap state store recognises those offsets as already
     processed and skips them, so ClickHouse still holds exactly 8000 rows.

An at-least-once sink would double every row here (16000). Pattern validation
(8000/8000) is what distinguishes the two.
"""
import json
import time
import urllib.error
import urllib.request

from pattern_explorer.orchestration.kafka_load import produce_partitioned
from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.wait import wait_for

CONNECT = "http://localhost:8083"
NAME = "clickhouse-sink"
N = 8000

CONFIG = {
    "connector.class": "com.clickhouse.kafka.connect.ClickHouseSinkConnector",
    "tasks.max": "1",
    "topics": "events",
    "hostname": "ch-01",
    "port": "8123",
    "database": "demo",
    "username": "default",
    "password": "",
    "ssl": "false",
    "exactlyOnce": "true",
    "key.converter": "org.apache.kafka.connect.storage.StringConverter",
    "value.converter": "org.apache.kafka.connect.json.JsonConverter",
    "value.converter.schemas.enable": "false",
    "consumer.override.auto.offset.reset": "earliest",
}


def api(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{CONNECT}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        return e.code, None


def wait_state(target, timeout=30):
    for _ in range(timeout):
        _, body = api("GET", f"/connectors/{NAME}/status")
        if body and body.get("connector", {}).get("state") == target:
            return
        time.sleep(1)
    raise RuntimeError(f"connector did not reach {target}")


def committed_offset():
    # /offsets returns [{"partition": {...}, "offset": {"kafka_offset": N}}, ...]
    _, body = api("GET", f"/connectors/{NAME}/offsets")
    if not body or not body.get("offsets"):
        return 0
    total = 0
    for o in body["offsets"]:
        off = o.get("offset") or {}
        total += off.get("kafka_offset", 0) if isinstance(off, dict) else (off or 0)
    return total


# 1. ingest
api("PUT", f"/connectors/{NAME}/config", CONFIG)
produce_partitioned("events", n=N, partitions=1)
ch = connect("ch-01")
wait_for(ch, "SELECT count() FROM demo.events", N, timeout=90)
print(f"initial ingest complete: {N} rows")

# 2. force reprocessing from offset 0
api("PUT", f"/connectors/{NAME}/stop")
wait_state("STOPPED")
api("DELETE", f"/connectors/{NAME}/offsets")
api("PUT", f"/connectors/{NAME}/resume")
wait_state("RUNNING")
print("offsets reset; connector reprocessing from 0")

# 3. wait until it has re-consumed everything (offsets back to end). This is the
# proof that reprocessing actually happened; without it the final count == N
# assertion is satisfied by the initial ingest alone and proves nothing.
committed = 0
for _ in range(90):
    committed = committed_offset()
    if committed >= N:
        break
    time.sleep(1)
else:
    raise SystemExit(
        f"reprocessing did not complete: committed offset {committed} < {N}. "
        "Offsets were not reset/reconsumed, so exactly-once is unproven."
    )
print(f"reprocessing done (committed offset {committed}); dedup must now hold")
time.sleep(3)   # let any (erroneous) duplicate inserts surface before verify
