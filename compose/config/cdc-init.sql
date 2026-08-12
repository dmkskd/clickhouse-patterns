-- Runs at ClickHouse first boot (single profile). The CDC connector needs its
-- state DB to exist before it connects, and a target DB for the replicated table.
CREATE DATABASE IF NOT EXISTS altinity_sink_connector;
CREATE DATABASE IF NOT EXISTS test;

-- The Altinity CDC patterns deliberately provide this target before the
-- connector starts. `orders` remains absent so the same run contrasts the
-- connector-created table with an existing ClickHouse target.
CREATE TABLE IF NOT EXISTS test.orders_existing
(
    id Int32,
    customer LowCardinality(Nullable(String)),
    amount Nullable(Int64),
    amount_band LowCardinality(String)
        MATERIALIZED if(ifNull(amount, 0) >= 250, 'high', 'standard'),
    _version UInt64,
    is_deleted UInt8
)
ENGINE = ReplacingMergeTree(_version, is_deleted)
ORDER BY id;
