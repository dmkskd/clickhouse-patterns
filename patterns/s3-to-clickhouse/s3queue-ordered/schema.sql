CREATE DATABASE IF NOT EXISTS demo;

-- Durable target for the ingested rows, tagged with the file each came from.
CREATE TABLE demo.events
(
    id          UInt64,
    kind        String,
    source_file String
)
ENGINE = MergeTree
ORDER BY id;

-- S3Queue in ordered mode. It keeps only a watermark in Keeper: the highest
-- filename processed. A file whose name sorts after the watermark is picked up; a
-- file that lands with an earlier name is ignored. Cheap, because only the
-- watermark is stored, but it assumes files arrive in lexical order.
CREATE TABLE demo.events_queue
(
    id   UInt64,
    kind String
)
ENGINE = S3Queue('http://minio:9000/clickhouse/queue/*.parquet', 'clickhouse', 'clickhouse_secret', 'Parquet')
SETTINGS mode = 'ordered', keeper_path = '/clickhouse/s3queue/events-ordered';

-- The pump: forward each processed row into the durable table, recording the
-- source file from the _file virtual column.
CREATE MATERIALIZED VIEW demo.events_mv TO demo.events AS
SELECT id, kind, _file AS source_file FROM demo.events_queue;
