CREATE DATABASE IF NOT EXISTS demo;

-- A declared table over a prefix that already holds objects. The table holds no
-- data of its own, and every SELECT reads the objects. The glob is what makes
-- the table cover the whole folder, and it is also what makes the table
-- read-only.
CREATE TABLE demo.exports_s3
(
    id   UInt64,
    kind String
)
ENGINE = S3('http://minio:9000/clickhouse/exports/*.parquet', 'clickhouse', 'clickhouse_secret', 'Parquet');

-- The write surface over the same prefix. A path with a glob cannot name the
-- object an INSERT would create, so writing needs a second declaration bound to
-- a single concrete key.
CREATE TABLE demo.exports_write
(
    id   UInt64,
    kind String
)
ENGINE = S3('http://minio:9000/clickhouse/exports/appended.parquet', 'clickhouse', 'clickhouse_secret', 'Parquet');
