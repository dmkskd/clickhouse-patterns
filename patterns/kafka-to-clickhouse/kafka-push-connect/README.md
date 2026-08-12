# Push ingestion via the ClickHouse Sink

Profiles: `single`, `kafka`, `connect`. Driver: `ch`.

The push counterpart to [kafka-ingest-replicated](../kafka-ingest-replicated/),
in which ClickHouse is a passive sink. A Kafka Connect worker runs the
[official ClickHouse Kafka Connect Sink](https://github.com/ClickHouse/clickhouse-kafka-connect)
and writes to ClickHouse over HTTP.

```
topic "events" -> Kafka Connect worker -HTTP-> demo.events (MergeTree)
                  (ClickHouseSinkConnector)     on ch
```

## Pull vs push

The [ClickHouse docs](https://clickhouse.com/docs/integrations/kafka) split the
options as:

| Method | Use when | Delivery |
|---|---|---|
| ClickPipes | ClickHouse Cloud | at-least-once |
| Kafka Connect Sink (this pattern) | high configurability, or already running Connect | exactly-once |
| Kafka engine (pull) | self-hosting, low barrier, or writing to Kafka | at-least-once |

The engine couples the consumer lifecycle to the ClickHouse server (rebalances,
assignment stalls), whereas Connect decouples ingestion and supports
exactly-once delivery.

## Run

```bash
just test kafka-push-connect
```

The `connect` service installs the sink plugin from Confluent Hub at start; the
healthcheck gates on `ClickHouseSinkConnector` appearing in `/connector-plugins`
before the load step registers it via the Connect REST API.

## Connector config

- `topics: events` + `database: demo` writes to `demo.events` (topic name = table name).
- `value.converter = JsonConverter`, `schemas.enable=false`: plain JSON mapped to columns.
- `exactlyOnce: false` here. For exactly-once see
  [kafka-push-exactly-once](../kafka-push-exactly-once/).

## Connector landscape

- [ClickHouse/clickhouse-kafka-connect](https://github.com/ClickHouse/clickhouse-kafka-connect)
  (this pattern): general Kafka topic to ClickHouse table sink.
- [Altinity/clickhouse-sink-connector](https://github.com/Altinity/clickhouse-sink-connector):
  a different tool for CDC replication (Debezium) from MySQL/Postgres/Mongo. See
  the `cdc-*` patterns.
