-- The old hour is one aggregate row. The two future rows remain detailed.
-- system.part_log records this GROUP BY TTL rewrite as TTLRecompressMerge.
SELECT *
FROM
(
    SELECT 'active_rows' AS check, toString(count()) AS value
    FROM demo.hourly_request_metrics
    UNION ALL
    SELECT 'current_detail_rows' AS check, toString(countIf(event_time >= toDateTime('2100-01-01 00:00:00'))) AS value
    FROM demo.hourly_request_metrics
    UNION ALL
    SELECT 'hourly_rollup_rows' AS check, toString(countIf(hour = toDateTime('2000-01-01 00:00:00'))) AS value
    FROM demo.hourly_request_metrics
    UNION ALL
    SELECT 'hourly_requests' AS check, toString(anyIf(requests, hour = toDateTime('2000-01-01 00:00:00'))) AS value
    FROM demo.hourly_request_metrics
    UNION ALL
    SELECT 'hourly_total_bytes' AS check, toString(anyIf(bytes, hour = toDateTime('2000-01-01 00:00:00'))) AS value
    FROM demo.hourly_request_metrics
    UNION ALL
    SELECT 'hourly_peak_bytes' AS check, toString(anyIf(max_bytes, hour = toDateTime('2000-01-01 00:00:00'))) AS value
    FROM demo.hourly_request_metrics
)
ORDER BY check;
