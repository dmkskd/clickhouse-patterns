-- The trade-off, quantified: 16000 physical rows stored (2x), but only 8000
-- distinct ids - the duplication is paid for in storage and collapsed at
-- query time (uniqExact here; FINAL would only help within a shard).
SELECT count() AS physical, uniqExact(id) AS distinct_ids
FROM demo.events_all;
