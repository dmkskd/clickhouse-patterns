"""Produce N events to the Kafka topic the CH consumer is subscribed to.

Runs on the host, talking to the broker's EXTERNAL listener (localhost:9092).
The topic is auto-created on first produce (single partition).
"""
import json
import os

from confluent_kafka import Producer

BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")
COUNT = int(os.environ.get("COUNT", "20000"))
KINDS = ("click", "view", "purchase")

producer = Producer({"bootstrap.servers": BOOTSTRAP})

for i in range(COUNT):
    producer.produce("events", value=json.dumps({"id": i, "kind": KINDS[i % 3]}))
    if i % 10000 == 0:
        producer.poll(0)

producer.flush()
print(f"produced {COUNT} messages to 'events' on {BOOTSTRAP}")
