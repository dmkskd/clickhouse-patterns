-- The 5-minute candle, produced entirely by the cascade: raw -> mv_1m ->
-- candles_1m (states) -> mv_5m -> candles_5m (states). ClickHouse never re-read
-- the raw trades to build this. The states are finalized here with -Merge and
-- must equal the same 5m window computed directly from raw.
SELECT
    symbol,
    toString(bucket)   AS bucket,
    argMinMerge(open)  AS open,
    max(high)          AS high,
    min(low)           AS low,
    argMaxMerge(close) AS close,
    sum(volume)        AS volume
FROM demo.candles_5m
GROUP BY symbol, bucket
ORDER BY symbol, bucket;
