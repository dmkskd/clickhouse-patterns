-- TTL recompression keeps every row unchanged. The part log proves that a
-- TTLRecompressMerge rewrote the part with the table's ZSTD(1) TTL codec.
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
    SELECT 'ttl_recompression_merges' AS check, toString(count()) AS value
    FROM system.part_log
    WHERE database = 'demo' AND table = 'recompressed_metrics'
      AND merge_reason = 'TTLRecompressMerge'
)
ORDER BY check;
