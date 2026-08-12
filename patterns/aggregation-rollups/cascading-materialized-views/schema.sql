-- Cascading materialized views: the 1m view reads RAW trades, but the 5m view
-- reads the 1m STATES table and re-aggregates them with the -MergeState
-- combinator. Each raw insert is aggregated once per level, not once per grain.
CREATE DATABASE IF NOT EXISTS demo;

CREATE TABLE demo.trades
(
    symbol LowCardinality(String),
    price  Float64,
    volume Float64,
    ts     DateTime64(3)
)
ENGINE = MergeTree
ORDER BY (symbol, ts);

-- 1-minute candle states, built from raw (same as the fan-out pattern).
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

CREATE MATERIALIZED VIEW demo.mv_1m TO demo.candles_1m AS
SELECT
    symbol,
    toStartOfMinute(ts)    AS bucket,
    argMinState(price, ts) AS open,
    max(price)             AS high,
    min(price)             AS low,
    argMaxState(price, ts) AS close,
    sum(volume)            AS volume
FROM demo.trades
GROUP BY symbol, bucket;

-- 5-minute candle states, built from the 1m STATES (this is the cascade).
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

-- Fires when mv_1m inserts rows into candles_1m. open/close are already
-- AggregateFunction states, so we cannot use argMinState(price) here; we merge
-- the incoming states into coarser states with the -MergeState combinator.
-- high/low/volume are plain SimpleAggregateFunction values, so they combine with
-- ordinary max/min/sum -- the additive case that needs no special combinator.
-- The inner subquery renames the 5-minute key to `bucket5` so it does not
-- collide with the source column `bucket`; the outer query presents it as
-- `bucket` to match the target table (materialized views map to a TO table by
-- column name).
CREATE MATERIALIZED VIEW demo.mv_5m TO demo.candles_5m AS
SELECT
    symbol,
    bucket5                 AS bucket,
    argMinMergeState(open)  AS open,
    max(high)               AS high,
    min(low)                AS low,
    argMaxMergeState(close) AS close,
    sum(volume)             AS volume
FROM
(
    SELECT
        symbol,
        toStartOfFiveMinutes(bucket) AS bucket5,
        open, high, low, close, volume
    FROM demo.candles_1m
)
GROUP BY symbol, bucket5;
