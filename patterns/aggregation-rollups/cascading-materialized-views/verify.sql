-- Verify both levels of the cascade. The 1m rollup is built from the raw
-- market data; the 5m rollup is built from the 1m aggregate states.
SELECT *
FROM
(
    SELECT
        '1m'                AS source,
        symbol,
        toString(bucket)    AS bucket,
        argMinMerge(open)   AS open,
        max(high)           AS high,
        min(low)            AS low,
        argMaxMerge(close)  AS close,
        sum(volume)         AS volume
    FROM demo.candles_1m
    GROUP BY symbol, bucket

    UNION ALL

    SELECT
        '5m'                AS source,
        symbol,
        toString(bucket)    AS bucket,
        argMinMerge(open)   AS open,
        max(high)           AS high,
        min(low)            AS low,
        argMaxMerge(close)  AS close,
        sum(volume)         AS volume
    FROM demo.candles_5m
    GROUP BY symbol, bucket
)
ORDER BY source, symbol, bucket;
