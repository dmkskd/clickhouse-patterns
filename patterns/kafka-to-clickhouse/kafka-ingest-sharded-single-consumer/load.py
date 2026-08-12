from pattern_explorer.orchestration.kafka_load import produce_partitioned

produce_partitioned("events", n=8000, partitions=4)
