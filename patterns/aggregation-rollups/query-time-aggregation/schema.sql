-- Query-time aggregation: store only raw ticks and compute the rollup on read.
-- There is no materialized view and no pre-aggregated table; verify.sql derives
-- the 1-minute OHLC candles directly from the raw rows with a GROUP BY.
CREATE DATABASE IF NOT EXISTS demo;

CREATE TABLE demo.ticks
(
    symbol LowCardinality(String),
    price  Float64,
    volume Float64,
    ts     DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (symbol, ts);
