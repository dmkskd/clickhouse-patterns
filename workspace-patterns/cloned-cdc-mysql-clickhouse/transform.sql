-- The Altinity connector has created test.orders by the time this file runs.
-- Propagate its CDC metadata so the transformed target handles later versions
-- and tombstones in the same way as the landing table.
CREATE TABLE IF NOT EXISTS test.orders_transformed
(
    id Int32,
    customer LowCardinality(Nullable(String)),
    amount Nullable(Decimal(12, 2)),
    amount_band LowCardinality(String),
    _version UInt64,
    is_deleted UInt8
)
ENGINE = ReplacingMergeTree(_version, is_deleted)
ORDER BY id;

CREATE MATERIALIZED VIEW IF NOT EXISTS test.orders_transform_mv
TO test.orders_transformed
AS
SELECT
    id,
    upper(customer) AS customer,
    toDecimal64(amount, 2) AS amount,
    if(ifNull(amount, 0) >= 250, 'high', 'standard') AS amount_band,
    _version,
    is_deleted
FROM test.orders;

INSERT INTO test.orders_transformed
SELECT
    id,
    upper(customer),
    toDecimal64(amount, 2),
    if(ifNull(amount, 0) >= 250, 'high', 'standard'),
    _version,
    is_deleted
FROM test.orders FINAL;
