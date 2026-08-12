-- Firing/resolved alerting inside ClickHouse, with hysteresis, producing to two
-- Kafka topics:
--   "status"  = level stream: current status per service, every tick
--   "alerts"  = edge stream: FIRING/RESOLVED only when the status changes
-- Hysteresis: fire at p90 > 1000ms, resolve only below 800ms (no flapping).
-- status_history is an internal state table: hysteresis needs the prior status.
CREATE DATABASE IF NOT EXISTS demo;

-- Inbound latency samples.
CREATE TABLE demo.latency_in (service String, latency_ms UInt32)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'latency',
         kafka_group_name = 'lat_in', kafka_format = 'JSONEachRow';

CREATE TABLE demo.latency_raw (service String, latency_ms UInt32, ts DateTime)
ENGINE = MergeTree ORDER BY (service, ts) TTL ts + INTERVAL 1 HOUR;

CREATE MATERIALIZED VIEW demo.mv_store TO demo.latency_raw AS
SELECT service, latency_ms, now() AS ts FROM demo.latency_in;

-- Internal state: current status per service each tick (needed for hysteresis).
CREATE TABLE demo.status_history
(
    service String, ts DateTime, p90 Float64,
    status String, prev_status String, is_transition UInt8, type String
) ENGINE = MergeTree ORDER BY (service, ts);

-- Topic "status": the level stream. Every status row is produced each tick.
CREATE TABLE demo.status_out (service String, status String, p90 Float64, at DateTime)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'status',
         kafka_group_name = 'status_out', kafka_format = 'JSONEachRow';

CREATE MATERIALIZED VIEW demo.mv_emit_status TO demo.status_out AS
SELECT service, status, p90, ts AS at FROM demo.status_history;

-- Topic "alerts": the edge stream. Only rows where the status changed.
CREATE TABLE demo.alerts_out (service String, type String, p90 Float64, at DateTime)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'alerts',
         kafka_group_name = 'alert_out', kafka_format = 'JSONEachRow';

CREATE MATERIALIZED VIEW demo.mv_emit_alerts TO demo.alerts_out AS
SELECT service, type, p90, ts AS at FROM demo.status_history WHERE is_transition = 1;

-- The evaluator: every 5s compute p90, apply hysteresis against the last status,
-- append the new status (flagged if it is a transition). The two MVs above then
-- produce it to the level and edge topics.
CREATE MATERIALIZED VIEW demo.mv_status
REFRESH EVERY 5 SECOND APPEND TO demo.status_history AS
SELECT
    service, ts, p90, status, prev_status,
    status != prev_status AS is_transition,
    multiIf(prev_status = 'ok'     AND status = 'firing', 'FIRING',
            prev_status = 'firing' AND status = 'ok',     'RESOLVED', '') AS type
FROM
(
    SELECT
        cur.service AS service,
        now() AS ts,
        cur.p90 AS p90,
        -- LEFT JOIN misses fill String with '' (not NULL), so treat '' as 'ok'.
        if(prev.last_status = '', 'ok', prev.last_status) AS prev_status,
        multiIf(cur.p90 > 1000, 'firing',
                cur.p90 < 800,  'ok',
                if(prev.last_status = '', 'ok', prev.last_status)) AS status
    FROM
    (
        SELECT service, quantile(0.9)(latency_ms) AS p90
        FROM demo.latency_raw
        WHERE ts > now() - INTERVAL 1 MINUTE
        GROUP BY service
    ) AS cur
    LEFT JOIN
    (
        SELECT service, argMax(status, ts) AS last_status
        FROM demo.status_history
        WHERE ts > now() - INTERVAL 10 MINUTE
        GROUP BY service
    ) AS prev ON cur.service = prev.service
);

-- Read both topics back so the test can assert them.
CREATE TABLE demo.status_in (service String, status String, p90 Float64, at DateTime)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'status',
         kafka_group_name = 'status_in', kafka_format = 'JSONEachRow';

CREATE TABLE demo.status_events (service String, status String, p90 Float64, at DateTime)
ENGINE = MergeTree ORDER BY (at, service);

CREATE MATERIALIZED VIEW demo.mv_status_store TO demo.status_events AS
SELECT service, status, p90, at FROM demo.status_in;

CREATE TABLE demo.alerts_in (service String, type String, p90 Float64, at DateTime)
ENGINE = Kafka
SETTINGS kafka_broker_list = 'kafka:9094', kafka_topic_list = 'alerts',
         kafka_group_name = 'alert_in', kafka_format = 'JSONEachRow';

CREATE TABLE demo.alerts_events (service String, type String, p90 Float64, at DateTime)
ENGINE = MergeTree ORDER BY (at, service);

CREATE MATERIALIZED VIEW demo.mv_alerts_store TO demo.alerts_events AS
SELECT service, type, p90, at FROM demo.alerts_in;
