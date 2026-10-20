-- One APPEND snapshot per refresh with new rows, each carrying the cursor.
SELECT
    operation,
    summary['added-records'] AS added_records,
    summary['total-records'] AS total_records,
    mapContains(summary, 'clickhouse.refresh-cursor') AS has_cursor
FROM system.iceberg_history
WHERE database = 'demo' AND table = 'lake_order_events'
ORDER BY made_current_at;
