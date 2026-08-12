"""Produce input events, wait for aggregation, then emit totals back to Kafka.

The emit step is `INSERT INTO demo.agg_out SELECT ...`, where agg_out is a Kafka
engine table. That INSERT produces messages to the output topic, which is the
write direction of the Kafka engine.
"""
from pattern_explorer.orchestration.kafka_load import produce_partitioned
from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.wait import wait_for

# 1. produce input events to "events" (id, kind); kind cycles click/view/purchase
produce_partitioned("events", n=8000, partitions=1)

ch = connect("ch")

# 2. wait until every input row has been consumed and aggregated
wait_for(ch, "SELECT sum(c) FROM demo.agg", 8000, timeout=90)
print("input aggregated (8000 rows)")

# 3. emit the current totals to the output topic (write direction of the engine)
ch.command("INSERT INTO demo.agg_out SELECT kind, sum(c) AS c FROM demo.agg GROUP BY kind")
print("emitted per-kind totals to the 'aggregates' topic")
