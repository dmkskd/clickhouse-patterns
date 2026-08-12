"""Shared Kafka producer used by runnable patterns.

Creates the topic with a fixed partition count and produces `n` events with
unique ids, placing each event on `partition = id % partitions` deterministically
(so a pattern can reason about exactly which partition owns which rows).
"""
from __future__ import annotations

import json
import os

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

KINDS = ("click", "view", "purchase")


def produce_partitioned(topic: str, n: int, partitions: int, bootstrap: str | None = None) -> None:
    bootstrap = bootstrap or os.environ.get("KAFKA_BOOTSTRAP", "localhost:9092")

    admin = AdminClient({"bootstrap.servers": bootstrap})
    for _, fut in admin.create_topics(
        [NewTopic(topic, num_partitions=partitions, replication_factor=1)]
    ).items():
        try:
            fut.result()  # block until created
        except Exception:
            pass          # already exists - fine

    producer = Producer({"bootstrap.servers": bootstrap})
    for i in range(n):
        producer.produce(
            topic,
            key=str(i),
            value=json.dumps({"id": i, "kind": KINDS[i % 3]}),
            partition=i % partitions,
        )
        if i % 5000 == 0:
            producer.poll(0)
    producer.flush()
    print(f"produced {n} messages across {partitions} partitions to {topic!r} on {bootstrap}")
