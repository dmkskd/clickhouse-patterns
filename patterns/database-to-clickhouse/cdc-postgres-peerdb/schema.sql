-- PeerDB creates test.orders. This second target already exists when the
-- mirror starts, proving that PeerDB can write into a compatible ClickHouse
-- schema that we own.
CREATE DATABASE IF NOT EXISTS test;

CREATE TABLE IF NOT EXISTS test.orders_existing
(
    id Int32,
    customer LowCardinality(String),
    amount Int64,
    amount_band LowCardinality(String)
        MATERIALIZED if(amount >= 250, 'high', 'standard'),
    _peerdb_synced_at DateTime64(9),
    _peerdb_is_deleted UInt8,
    _peerdb_version UInt64
)
ENGINE = ReplacingMergeTree(_peerdb_version)
ORDER BY id;
