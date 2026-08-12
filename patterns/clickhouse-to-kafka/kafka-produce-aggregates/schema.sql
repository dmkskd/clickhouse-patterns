-- Round trip: consume "events", aggregate, produce totals back to "aggregates".
-- Shows the Kafka engine in both directions (read and write).
CREATE DATABASE IF NOT EXISTS demo;

-- Consume the input topic.
CREATE TABLE demo.events_in (id UInt64, kind String)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'events',
         kafka_group_name = 'rt_in', kafka_format = 'JSONEachRow';

-- Accumulator. SummingMergeTree adds `c` for rows with the same `kind` on merge,
-- so sum(c) GROUP BY kind is the correct total whether or not a merge has run.
CREATE TABLE demo.agg (kind String, c UInt64)
ENGINE = SummingMergeTree ORDER BY kind;

-- Consume -> per-block partial counts -> accumulator.
CREATE MATERIALIZED VIEW demo.mv_agg TO demo.agg AS
SELECT kind, count() AS c FROM demo.events_in GROUP BY kind;

-- Producer. INSERT INTO this table writes messages to the "aggregates" topic.
CREATE TABLE demo.agg_out (kind String, c UInt64)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'aggregates',
         kafka_group_name = 'rt_out', kafka_format = 'JSONEachRow';

-- Read the output topic back so the test can assert what was produced.
CREATE TABLE demo.agg_back (kind String, c UInt64)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'aggregates',
         kafka_group_name = 'rt_back', kafka_format = 'JSONEachRow';

CREATE TABLE demo.agg_store (kind String, c UInt64)
ENGINE = MergeTree ORDER BY kind;

CREATE MATERIALIZED VIEW demo.mv_store TO demo.agg_store AS
SELECT kind, c FROM demo.agg_back;
