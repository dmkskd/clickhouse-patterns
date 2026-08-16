-- Expected evidence:
-- * the table definition already carries the new 30-day policy;
-- * only January 2025, the materialized month, lost its expired rows, so the
--   change was staged rather than applied to all history at once;
-- * February 2025's active part still carries the delete deadline computed
--   from the previous five-year policy, which is why a background TTL merge
--   does not consider it expired yet;
-- * exactly one mutation ran, the MATERIALIZE TTL for that single month.
SELECT *
FROM
(
    SELECT 'table_ttl_expression' AS check,
           trimBoth(splitByString(' SETTINGS',
               splitByString(' TTL ', replaceAll(any(create_table_query), '\n', ' '))[2])[1]) AS value
    FROM system.tables
    WHERE database = 'demo' AND name = 'events'
    UNION ALL
    SELECT 'remaining_rows' AS check, toString(count()) AS value
    FROM demo.events
    UNION ALL
    SELECT 'rows_in_january_materialized' AS check, toString(count()) AS value
    FROM demo.events
    WHERE toYYYYMM(event_time) = 202501
    UNION ALL
    SELECT 'rows_in_february_staged' AS check, toString(count()) AS value
    FROM demo.events
    WHERE toYYYYMM(event_time) = 202502
    UNION ALL
    SELECT 'february_delete_deadline_year' AS check,
           toString(toYear(max(delete_ttl_info_max))) AS value
    FROM system.parts
    WHERE database = 'demo' AND table = 'events' AND active
      AND partition = '202502'
    UNION ALL
    SELECT 'finished_mutations' AS check, toString(countIf(is_done)) AS value
    FROM system.mutations
    WHERE database = 'demo' AND table = 'events'
)
ORDER BY check;
