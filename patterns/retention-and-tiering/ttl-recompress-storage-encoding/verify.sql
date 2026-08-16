-- The active part's default codec must be the codec named in the TTL rule.
-- `Default` in the explicit Delta/Gorilla column codecs resolves to that codec.
-- The part log separately proves that ClickHouse performed the TTL rewrite.
SELECT *
FROM
(
    SELECT 'rows' AS check, toString(count()) AS value
    FROM demo.recompressed_metrics
    UNION ALL
    SELECT 'active_parts' AS check, toString(count()) AS value
    FROM system.parts
    WHERE database = 'demo' AND table = 'recompressed_metrics' AND active
    UNION ALL
    SELECT 'active_part_codec' AS check, any(default_compression_codec) AS value
    FROM system.parts
    WHERE database = 'demo' AND table = 'recompressed_metrics' AND active
    UNION ALL
    SELECT 'ttl_recompression_merges' AS check, toString(count()) AS value
    FROM system.part_log
    WHERE database = 'demo' AND table = 'recompressed_metrics'
      AND merge_reason = 'TTLRecompressMerge'
)
ORDER BY check;
