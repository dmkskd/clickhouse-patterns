-- Materialized view rollups (fan-out): each time bucket is its own incremental
-- MV, a trigger on demo.ticks that aggregates each inserted block into
-- aggregate-function states in an AggregatingMergeTree. The 1m and 5m views
-- both trigger on demo.ticks directly.
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

-- 1-minute candles. open/close keep an AggregateFunction state (needed for
-- argMin/argMax); high/low/volume use SimpleAggregateFunction, which stores a
-- plain, readable value you can SELECT directly.
CREATE TABLE demo.candles_1m
(
    symbol LowCardinality(String),
    bucket DateTime,
    open   AggregateFunction(argMin, Float64, DateTime64(3)),
    high   SimpleAggregateFunction(max, Float64),
    low    SimpleAggregateFunction(min, Float64),
    close  AggregateFunction(argMax, Float64, DateTime64(3)),
    volume SimpleAggregateFunction(sum, Float64)
)
ENGINE = AggregatingMergeTree
ORDER BY (symbol, bucket);

-- Triggers once per inserted block of raw ticks; writes one partial state per
-- (symbol, minute) present in that block. Different inserts -> different parts.
CREATE MATERIALIZED VIEW demo.mv_1m TO demo.candles_1m AS
SELECT
    symbol,
    toStartOfMinute(ts)    AS bucket,
    argMinState(price, ts) AS open,
    max(price)        AS high,
    min(price)        AS low,
    argMaxState(price, ts) AS close,
    sum(volume)       AS volume
FROM demo.ticks
GROUP BY symbol, bucket;

-- 5-minute candle states, ALSO triggered by raw tick inserts (this is the fan-out:
-- the 5m view triggers on the same demo.ticks inserts rather than reading
-- candles_1m).
CREATE TABLE demo.candles_5m
(
    symbol LowCardinality(String),
    bucket DateTime,
    open   AggregateFunction(argMin, Float64, DateTime64(3)),
    high   SimpleAggregateFunction(max, Float64),
    low    SimpleAggregateFunction(min, Float64),
    close  AggregateFunction(argMax, Float64, DateTime64(3)),
    volume SimpleAggregateFunction(sum, Float64)
)
ENGINE = AggregatingMergeTree
ORDER BY (symbol, bucket);

CREATE MATERIALIZED VIEW demo.mv_5m TO demo.candles_5m AS
SELECT
    symbol,
    toStartOfFiveMinutes(ts) AS bucket,
    argMinState(price, ts)   AS open,
    max(price)          AS high,
    min(price)          AS low,
    argMaxState(price, ts)   AS close,
    sum(volume)         AS volume
FROM demo.ticks
GROUP BY symbol, bucket;
