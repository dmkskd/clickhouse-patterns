-- Expected evidence:
-- * the table definition already carries the new 30-day policy;
-- * only the older month, the one that was materialized, lost its rows, so the
--   change reached part of the history rather than all of it;
-- * the recent month's active part still carries the delete deadline computed
--   from the one-year policy, which is why a background TTL merge does not
--   consider it expired yet;
-- * exactly one mutation ran, the MATERIALIZE TTL for that single month.
-- The two months are derived the same way the loader derives them, so the
-- checks hold on any date the pattern runs.
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
    SELECT 'rows_in_materialized_month' AS check, toString(count()) AS value
    FROM demo.events
    WHERE toYYYYMM(event_time) = toYYYYMM(now() - INTERVAL 150 DAY)
    UNION ALL
    SELECT 'rows_in_staged_month' AS check, toString(count()) AS value
    FROM demo.events
    WHERE toYYYYMM(event_time) = toYYYYMM(now() - INTERVAL 120 DAY)
    UNION ALL
    -- The staged part is still due for deletion roughly a year after its rows
    -- were written, not 30 days after: its TTL metadata predates the change.
    SELECT 'staged_deadline_still_months_away' AS check,
           toString(countIf(delete_ttl_info_max > now() + INTERVAL 180 DAY)) AS value
    FROM system.parts
    WHERE database = 'demo' AND table = 'events' AND active
    UNION ALL
    SELECT 'finished_mutations' AS check, toString(countIf(is_done)) AS value
    FROM system.mutations
    WHERE database = 'demo' AND table = 'events'
)
ORDER BY check;
