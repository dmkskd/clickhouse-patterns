-- The totals as they came back from the output topic, read directly (no re-sum).
-- One row per kind, each holding the summed count produced by ClickHouse.
-- Wrong summation shows as wrong values; a split/duplicate emit shows as extra rows.
SELECT kind, c AS total
FROM demo.agg_store
ORDER BY kind;
