-- Replicated target so the connector's writes to ch-01 are replicated to ch-02.
CREATE DATABASE IF NOT EXISTS demo ON CLUSTER patterns;

CREATE TABLE demo.events ON CLUSTER patterns (id UInt64, kind String)
ENGINE = ReplicatedMergeTree ORDER BY id;
