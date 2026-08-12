-- Exactly-once held across full reprocessing: 8000 physical rows, 8000 distinct.
-- (An at-least-once sink would show 16000 physical here.)
SELECT count() AS rows, uniqExact(id) AS distinct_ids
FROM demo.events;
