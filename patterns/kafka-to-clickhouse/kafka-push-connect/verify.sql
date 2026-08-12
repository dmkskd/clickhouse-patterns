-- All 8000 rows pushed in, no duplicates (no failures were injected).
SELECT count() AS rows, uniqExact(id) AS distinct_ids
FROM demo.events;
