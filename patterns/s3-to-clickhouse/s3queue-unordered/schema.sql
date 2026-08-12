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

-- S3Queue in unordered mode. It keeps the full SET of processed files in Keeper,
-- so a new file is ingested regardless of its name, even one that sorts before an
-- already-processed file. This handles out-of-order arrivals; the cost is that the
-- tracked-file set grows, bounded by s3queue_tracked_files_limit and a TTL. The
-- managed ClickPipes equivalent uses S3 event notifications instead of polling.
CREATE TABLE demo.events_queue
(
    id   UInt64,
    kind String
)
ENGINE = S3Queue('http://minio:9000/clickhouse/queue/*.parquet', 'clickhouse', 'clickhouse_secret', 'Parquet')
SETTINGS mode = 'unordered', keeper_path = '/clickhouse/s3queue/events-unordered';

-- The pump: forward each processed row into the durable table, recording the
-- source file from the _file virtual column.
CREATE MATERIALIZED VIEW demo.events_mv TO demo.events AS
SELECT id, kind, _file AS source_file FROM demo.events_queue;
