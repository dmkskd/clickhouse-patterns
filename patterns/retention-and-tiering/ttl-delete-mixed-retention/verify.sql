-- The DEBUG rows have expired. The retained INFO rows show the materialized
-- multiIf result, proving that the retention policy is calculated per row.
SELECT *
FROM
(
    SELECT 'remaining_rows' AS check, toString(count()) AS value
    FROM demo.variable_retention_events
    UNION ALL
    SELECT 'remaining_level' AS check, any(log_level) AS value
    FROM demo.variable_retention_events
    UNION ALL
    SELECT 'future_expiries' AS check, toString(countIf(expires_at > now())) AS value
    FROM demo.variable_retention_events
    UNION ALL
    SELECT 'active_parts' AS check, toString(count()) AS value
    FROM system.parts
    WHERE database = 'demo' AND table = 'variable_retention_events' AND active
)
ORDER BY check;
