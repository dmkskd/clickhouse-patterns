-- The comparison saved after each stage: identical after the export, then
-- two differences after the update and delete in the source.
SELECT stage_name, event_id, clickhouse_amount, iceberg_amount, state
FROM demo.drift_check
ORDER BY stage, event_id;
