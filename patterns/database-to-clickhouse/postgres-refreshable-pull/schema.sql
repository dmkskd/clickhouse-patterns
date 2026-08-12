-- Level 1's declaration, unchanged: a zero-storage handle on the Postgres table.
-- On its own, every read of this goes to Postgres. Here it is read once per
-- refresh instead, by exactly one reader.
CREATE DATABASE IF NOT EXISTS test;

CREATE TABLE IF NOT EXISTS test.pg_orders
(
    id       Int32,
    customer String,
    amount   Int32
)
ENGINE = PostgreSQL('postgres:5432', 'test', 'orders', 'postgres', 'postgres');

-- On each tick ClickHouse reruns this SELECT against
-- Postgres and atomically swaps the result into a local MergeTree. A real
-- deployment would refresh every minute or few minutes; 5s here keeps the
-- test fast, and nothing about the mechanism changes with the interval.
--
-- Without APPEND, each refresh REPLACES the entire table, which is why this is
-- lighter than CDC. A row deleted in Postgres is simply not in the next result,
-- so nothing needs a tombstone, a _version comparison, or FINAL on read. The
-- table is always a clean, complete, slightly stale copy.
--
-- It is also the constraint: every refresh re-reads every row, so this only
-- stays cheap while the source table stays small.
CREATE MATERIALIZED VIEW IF NOT EXISTS test.orders
REFRESH EVERY 5 SECOND
ENGINE = MergeTree ORDER BY id
AS
SELECT
    id,
    upper(customer)                              AS customer,
    toDecimal64(amount, 2)                       AS amount,
    if(amount >= 250, 'high', 'standard')        AS amount_band
FROM test.pg_orders;

-- ── Variant: keep the history instead of replacing it ──────────────────────
-- Same source, same schedule, one keyword different. APPEND adds each refresh
-- to the table rather than replacing it, so the result is a periodic snapshot:
-- the state of the source sampled once per tick, stamped with the time it was
-- observed. now64() is evaluated once per refresh, so a whole snapshot shares
-- one timestamp.
--
-- The cost is the mirror image of the full replace above: nothing is ever
-- discarded, and every tick writes the entire table again whether or not
-- anything changed. Storage grows as rows x refreshes, so a real deployment
-- needs a coarser interval and a TTL.
CREATE MATERIALIZED VIEW IF NOT EXISTS test.orders_history
REFRESH EVERY 5 SECOND APPEND
ENGINE = MergeTree ORDER BY (id, snapshot_at)
AS
SELECT
    now64(3)                                     AS snapshot_at,
    id,
    upper(customer)                              AS customer,
    toDecimal64(amount, 2)                       AS amount,
    if(amount >= 250, 'high', 'standard')        AS amount_band
FROM test.pg_orders;

-- Current state, read back out of the history. Selecting the whole newest
-- snapshot is what keeps deletes working: a row deleted in Postgres is absent
-- from that snapshot and so absent here.
--
-- Resolving per key instead - argMax(...) ... GROUP BY id - looks equivalent
-- and is not: a deleted row keeps its last observed values forever, because no
-- later snapshot exists to overrule them.
CREATE VIEW IF NOT EXISTS test.orders_latest AS
SELECT snapshot_at, id, customer, amount, amount_band
FROM test.orders_history
WHERE snapshot_at = (SELECT max(snapshot_at) FROM test.orders_history);
