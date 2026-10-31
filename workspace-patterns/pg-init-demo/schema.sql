-- Three ways to read Postgres from ClickHouse without copying anything.
-- Every statement below is a declaration: no rows move until a SELECT runs,
-- and each SELECT is a fresh round trip to Postgres.
--
-- The names are deliberately unalike, because the three paths are easy to
-- confuse: `orders_table_engine` is a table, `pg_schema` is a database.
CREATE DATABASE IF NOT EXISTS test;

-- 1. Table engine. One ClickHouse table you declare yourself, bound to one
--    Postgres table. You own the column types, so you can widen or pin them.
CREATE TABLE IF NOT EXISTS test.orders_table_engine
(
    id       Int32,
    customer String,
    amount   Int32
)
ENGINE = PostgreSQL('postgres:5432', 'test', 'orders', 'postgres', 'postgres');

-- 2. Database engine. The entire Postgres schema in one statement. Nothing is
--    declared per table: names and types are resolved when a query runs, so a
--    table added in Postgres needs no ClickHouse DDL.
DROP DATABASE IF EXISTS pg_schema;
CREATE DATABASE pg_schema
ENGINE = PostgreSQL('postgres:5432', 'test', 'postgres', 'postgres');

-- 3. Table function. No object at all; the connection lives in the query text.
--    See verify.sql, which calls postgresql() inline.
