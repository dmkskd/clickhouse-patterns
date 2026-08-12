from pattern_explorer.orchestration.kafka_load import produce_partitioned

# 8000 unique ids across 4 partitions (2000 each), partition = id % 4.
# The engine's modulo affinity then routes partitions 0,2 to shard 1 and 1,3 to
# shard 2, so each shard stores exactly 4000 rows.
produce_partitioned("events", n=8000, partitions=4)
