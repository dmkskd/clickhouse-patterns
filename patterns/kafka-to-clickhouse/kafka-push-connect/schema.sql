-- PUSH model: no Kafka engine, no materialized view. The target table is a
-- plain MergeTree that the connector writes into over HTTP. The table name
-- must match the Kafka topic ('events') in the connector's database ('demo').
CREATE DATABASE IF NOT EXISTS demo;

CREATE TABLE demo.events (id UInt64, kind String)
ENGINE = MergeTree ORDER BY id;
