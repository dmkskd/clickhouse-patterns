-- Prove the complete id set and its deterministic round-robin kind mapping.
-- count = uniqExact plus bounds 0..19999 rules out both gaps and duplicates.
SELECT
    count() AS rows,
    uniqExact(id) AS distinct_ids,
    min(id) AS min_id,
    max(id) AS max_id,
    countIf(kind = 'click') AS clicks,
    countIf(kind = 'purchase') AS purchases,
    countIf(kind = 'view') AS views
FROM demo.events;
