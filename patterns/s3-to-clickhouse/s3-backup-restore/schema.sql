CREATE DATABASE IF NOT EXISTS demo;

-- The worker's table. In production a separate clickhouse-local (or any
-- ClickHouse) instance builds this off the serving cluster, then backs it up to
-- S3. Here it stands in for that offline worker. The serving table is created by
-- RESTORE, so it is not declared here.
CREATE TABLE demo.events_staging
(
    id   UInt64,
    kind String
)
ENGINE = MergeTree
ORDER BY id;
