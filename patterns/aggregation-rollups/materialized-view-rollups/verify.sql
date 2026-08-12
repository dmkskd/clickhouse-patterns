-- Read the 1-minute candles back from the stored states. Each (symbol, minute)
-- was written by up to three separate MV firings (one per insert batch), so the
-- states live in different parts; the -Merge combinators recombine them into one
-- correct candle. The result must equal query-time-aggregation's ground truth.
SELECT
    symbol,
    toString(bucket)   AS bucket,
    argMinMerge(open)  AS open,
    max(high)          AS high,
    min(low)           AS low,
    argMaxMerge(close) AS close,
    sum(volume)        AS volume
FROM demo.candles_1m
GROUP BY symbol, bucket
ORDER BY symbol, bucket;
