-- PeerDB has already created test.orders by the time this file runs. Keep the
-- CDC version and deletion marker so transformed rows retain current-state
-- semantics after updates and deletes.
CREATE TABLE IF NOT EXISTS test.orders_transformed
(
    id Int32,
    customer LowCardinality(String),
    amount Decimal(12, 2),
    amount_band LowCardinality(String),
    _peerdb_is_deleted UInt8,
    _peerdb_version UInt64
)
ENGINE = ReplacingMergeTree(_peerdb_version)
ORDER BY id;

CREATE MATERIALIZED VIEW IF NOT EXISTS test.orders_transform_mv
TO test.orders_transformed
AS
SELECT
    id,
    upper(customer) AS customer,
    toDecimal64(amount, 2) AS amount,
    if(amount >= 250, 'high', 'standard') AS amount_band,
    _peerdb_is_deleted,
    _peerdb_version
FROM test.orders;

-- The MV is installed after PeerDB's initial snapshot because its source table
-- did not exist earlier. Backfill the snapshot before streaming new changes.
INSERT INTO test.orders_transformed
SELECT
    id,
    upper(customer),
    toDecimal64(amount, 2),
    if(amount >= 250, 'high', 'standard'),
    _peerdb_is_deleted,
    _peerdb_version
FROM test.orders FINAL;
