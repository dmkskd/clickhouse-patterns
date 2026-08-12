"""Drive a full firing then resolved sequence for one service.

  phase 1: checkout latency high (p90 > 1000) -> FIRING ; health stays healthy
  phase 2: checkout floods with low latencies (p90 < 800) -> RESOLVED
"""
import json

from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.wait import wait_for

BOOTSTRAP = "localhost:9092"

admin = AdminClient({"bootstrap.servers": BOOTSTRAP})
for _, fut in admin.create_topics([NewTopic("latency", 1, 1)]).items():
    try:
        fut.result()
    except Exception:
        pass

p = Producer({"bootstrap.servers": BOOTSTRAP})


def produce(service, base, spread, n):
    for i in range(n):
        p.produce("latency", json.dumps({"service": service, "latency_ms": base + (i % spread)}))
    p.flush()


# phase 1: checkout breaches, health healthy
produce("checkout", 1100, 500, 300)   # ~1100-1599ms -> p90 > 1000
produce("health",     20,  60, 300)   # ~20-79ms     -> healthy
print("phase 1: breaching checkout + healthy health")

ch = connect("ch")
wait_for(ch,
         "SELECT count() FROM demo.alerts_events WHERE service = 'checkout' AND type = 'FIRING'",
         1, timeout=45)
print("FIRING observed for checkout")

# phase 2: flood checkout with low latencies so p90 drops below the 800 resolve line
produce("checkout", 20, 60, 3000)
print("phase 2: recovery samples for checkout")
