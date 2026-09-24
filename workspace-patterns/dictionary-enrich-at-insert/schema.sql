CREATE DATABASE IF NOT EXISTS test;

-- The dimension, held in ClickHouse memory and keyed for point lookups. HASHED
-- keeps every element resident, which is the right layout while the dimension
-- fits; a large one needs SPARSE_HASHED or CACHE instead.
--
-- LIFETIME is the only refresh mechanism here: ClickHouse re-runs the source
-- query once the interval expires. 1-2 seconds keeps the test fast and is far
-- shorter than a real deployment would use. Without an invalidate_query, every
-- expiry re-reads the whole dimension, so the interval is a cost as well as a
-- freshness bound.
CREATE DICTIONARY IF NOT EXISTS test.customers_dict
(
    id   UInt64,
    name String,
    tier String
)
PRIMARY KEY id
SOURCE(POSTGRESQL(
    host 'postgres' port 5432
    user 'postgres' password 'postgres'
    db 'test' table 'customers'
))
LAYOUT(HASHED())
LIFETIME(MIN 1 MAX 2);

-- Facts as received: a customer_id and nothing about the customer.
CREATE TABLE IF NOT EXISTS test.events_raw
(
    event_id    UInt64,
    customer_id UInt64,
    amount      Decimal(10, 2),
    ts          DateTime
)
ENGINE = MergeTree
ORDER BY (customer_id, event_id);

-- Design A: resolve once, at insert, and store the result. The tier column is a
-- stored value, so it can lead the ORDER BY and a read never touches the
-- dimension. It is also fixed: a later change in Postgres does not reach it.
CREATE TABLE IF NOT EXISTS test.events_enriched
(
    event_id      UInt64,
    customer_id   UInt64,
    customer_name String,
    customer_tier LowCardinality(String),
    amount        Decimal(10, 2),
    ts            DateTime
)
ENGINE = MergeTree
ORDER BY (customer_tier, event_id);

-- dictGet runs per inserted block, against the dictionary as it stands at that
-- moment. A key the dictionary does not hold is not an error: dictGet returns
-- the attribute type's default, so an unknown customer_id is stored as ''.
CREATE MATERIALIZED VIEW IF NOT EXISTS test.events_enrich_mv
TO test.events_enriched
AS
SELECT
    event_id,
    customer_id,
    dictGetString('test.customers_dict', 'name', customer_id) AS customer_name,
    dictGetString('test.customers_dict', 'tier', customer_id) AS customer_tier,
    amount,
    ts
FROM test.events_raw;

-- Design B: same dictionary, same function, resolved on every read instead.
-- Stores nothing, so a corrected dimension row corrects the whole history at
-- once, and each scan pays a lookup per row.
CREATE VIEW IF NOT EXISTS test.events_current_tier AS
SELECT
    event_id,
    customer_id,
    dictGetString('test.customers_dict', 'name', customer_id) AS customer_name,
    dictGetString('test.customers_dict', 'tier', customer_id) AS customer_tier,
    amount,
    ts
FROM test.events_raw;
