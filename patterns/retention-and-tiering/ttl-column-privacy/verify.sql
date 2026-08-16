-- The events and their useful dimensions remain. Column TTL has replaced the
-- two sensitive String values with their default, the empty string.
--
-- For physical confirmation, inspect system.parts_columns for the active part
-- and system.part_log for the TTL merge that rewrote it.
SELECT *
FROM
(
    SELECT 'remaining_rows' AS check, toString(count()) AS value
    FROM demo.access_events
    UNION ALL
    SELECT 'preserved_statuses' AS check, toString(countIf(status IN ('200', '404'))) AS value
    FROM demo.access_events
    UNION ALL
    SELECT 'expired_ip_values' AS check, toString(countIf(client_ip = '')) AS value
    FROM demo.access_events
    UNION ALL
    SELECT 'expired_user_agents' AS check, toString(countIf(user_agent = '')) AS value
    FROM demo.access_events
)
ORDER BY check;
