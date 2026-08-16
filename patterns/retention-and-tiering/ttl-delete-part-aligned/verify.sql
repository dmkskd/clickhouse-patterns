-- Expected evidence:
-- * the expired partition has disappeared and exactly two current rows remain;
-- * there is one active part, rather than a rewritten mixture of expired and current rows;
-- * that current part remains at level 0 with no mutation suffix. The loader does not
--   run MATERIALIZE TTL, so this distinguishes a background whole-part drop
--   from a forced mutation-based rewrite.
SELECT *
FROM
(
    SELECT 'remaining_rows' AS check, toString(count()) AS value
    FROM demo.events
    UNION ALL
    SELECT 'active_parts' AS check, toString(count()) AS value
    FROM system.parts
    WHERE database = 'demo' AND table = 'events' AND active
    UNION ALL
    SELECT 'remaining_batch' AS check, any(batch) AS value
    FROM demo.events
    UNION ALL
    SELECT 'current_part_level' AS check, toString(max(level)) AS value
    FROM system.parts
    WHERE database = 'demo' AND table = 'events' AND active
    UNION ALL
    SELECT 'current_part_has_mutation_suffix' AS check,
           toString(countIf(length(splitByChar('_', name)) > 4)) AS value
    FROM system.parts
    WHERE database = 'demo' AND table = 'events' AND active
)
ORDER BY check;
