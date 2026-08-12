from pattern_explorer.orchestration.kafka_load import produce_partitioned

# 8000 unique ids across 4 partitions (2000 each), partition = id % 4.
produce_partitioned("events", n=8000, partitions=4)
