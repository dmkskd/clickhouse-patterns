-- Streaming alert inside ClickHouse: consume latency samples, keep a rolling
-- window, and produce an alert to Kafka when a service's p90 exceeds 1000ms.
-- No external stream processor keeps state; ClickHouse does.
CREATE DATABASE IF NOT EXISTS demo;

-- Inbound: latency samples from the "latency" topic.
CREATE TABLE demo.latency_in (service String, latency_ms UInt32)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'latency',
         kafka_group_name = 'lat_in', kafka_format = 'JSONEachRow';

-- State: raw samples, stamped on ingest, kept for a short retention.
CREATE TABLE demo.latency_raw (service String, latency_ms UInt32, ts DateTime)
ENGINE = MergeTree ORDER BY (service, ts) TTL ts + INTERVAL 1 HOUR;

CREATE MATERIALIZED VIEW demo.mv_store TO demo.latency_raw AS
SELECT service, latency_ms, now() AS ts FROM demo.latency_in;

-- Outbound: the "alerts" topic. INSERT into this table produces a message.
CREATE TABLE demo.alerts_out (service String, p90 Float64)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'alerts',
         kafka_group_name = 'alert_out', kafka_format = 'JSONEachRow';

-- The sender: every 5s, evaluate p90 over the rolling window and, for any
-- service above threshold, APPEND (produce) an alert to the output topic.
CREATE MATERIALIZED VIEW demo.mv_alerts
REFRESH EVERY 5 SECOND APPEND TO demo.alerts_out AS
SELECT service, quantile(0.9)(latency_ms) AS p90
FROM demo.latency_raw
WHERE ts > now() - INTERVAL 1 MINUTE
GROUP BY service
HAVING p90 > 1000;

-- Read the alerts back so the test can assert them. The refreshable MV emits
-- every 5s, so a breaching service appears repeatedly; ReplacingMergeTree keyed
-- by service collapses those to one row.
CREATE TABLE demo.alerts_in (service String, p90 Float64)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'alerts',
         kafka_group_name = 'alert_in', kafka_format = 'JSONEachRow';

CREATE TABLE demo.alerts_store (service String, p90 Float64)
ENGINE = ReplacingMergeTree ORDER BY service;

CREATE MATERIALIZED VIEW demo.mv_alerts_store TO demo.alerts_store AS
SELECT service, p90 FROM demo.alerts_in;
