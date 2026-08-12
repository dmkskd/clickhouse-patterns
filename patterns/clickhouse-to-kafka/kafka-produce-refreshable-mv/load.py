"""Produce latency samples for two services: one breaching p90>1000ms, one not.

  checkout: ~1100-1600ms  -> p90 well above 1000 -> alert
  health:   ~20-80ms      -> p90 well below 1000 -> no alert
"""
import json

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

BOOTSTRAP = "localhost:9092"

admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
for _, fut in admin.create_topics([NewTopic("latency", 1, 1)]).items():
    try:
        fut.result()
    except Exception:
        pass

p = Producer({"bootstrap.servers": BOOTSTRAP})
for i in range(300):
    p.produce("latency", json.dumps({"service": "checkout", "latency_ms": 1100 + (i % 500)}))
    p.produce("latency", json.dumps({"service": "health",   "latency_ms": 20 + (i % 60)}))
    if i % 100 == 0:
        p.poll(0)
p.flush()
print("produced 300 latency samples each for checkout and health")
