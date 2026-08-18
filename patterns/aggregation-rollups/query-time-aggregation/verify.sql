-- Two rollups, both computed on read straight from the raw ticks: per-minute
-- and per-5-minute. Nothing is precomputed, so each is just its own GROUP BY
-- over the raw rows. open/close are the first/last price by time (argMin/argMax
-- on ts); high/low/volume are max/min/sum. The union is wrapped so the ORDER BY
-- sorts the whole result deterministically (a bare ORDER BY after UNION ALL
-- would bind to the last SELECT only).
SELECT grain, symbol, bucket, open, high, low, close, volume
FROM
(
    SELECT '1m' AS grain, symbol, toString(toStartOfMinute(ts)) AS bucket,
           argMin(price, ts) AS open, max(price) AS high, min(price) AS low,
           argMax(price, ts) AS close, sum(volume) AS volume
    FROM demo.ticks
    GROUP BY symbol, toStartOfMinute(ts)
    UNION ALL
    SELECT '5m' AS grain, symbol, toString(toStartOfFiveMinutes(ts)) AS bucket,
           argMin(price, ts) AS open, max(price) AS high, min(price) AS low,
           argMax(price, ts) AS close, sum(volume) AS volume
    FROM demo.ticks
    GROUP BY symbol, toStartOfFiveMinutes(ts)
)
ORDER BY grain, symbol, bucket;
