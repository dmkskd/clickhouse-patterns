-- This pattern owns its target table, so both the CDC metadata and the Kafka
-- metadata are declared here rather than inferred by the connector.
--
-- Debezium's envelope is unwrapped in flight by an SMT (see load.py), so rows
-- arrive flat. Two fields survive from the envelope: __lsn orders competing
-- versions, and __deleted marks a removal.
--
-- The __topic/__partition/__offset/__timestamp columns are added on the sink
-- side by the InsertField SMT. They cost very little to keep: the topic is
-- constant, and the partition and offset are constant or monotonic within a
-- block, so the codecs below compress them to almost nothing. In exchange every
-- row is traceable back to the exact Kafka record that produced it.
--
-- Non-key columns are nullable because Postgres' default replica identity sends
-- only the key for a delete, so the rewritten delete event carries no customer
-- or amount.
CREATE DATABASE IF NOT EXISTS test;

CREATE TABLE IF NOT EXISTS test.orders
(
    id          Int32,
    customer    Nullable(String),
    amount      Nullable(Int32),
    __lsn       UInt64,
    __deleted   String,
    __topic     LowCardinality(String),
    __partition UInt32 CODEC(DoubleDelta, ZSTD(1)),
    __offset    UInt64 CODEC(DoubleDelta, ZSTD(1)),
    __timestamp DateTime64(3) CODEC(DoubleDelta, ZSTD(1))
)
ENGINE = ReplacingMergeTree(__lsn)
ORDER BY id;
