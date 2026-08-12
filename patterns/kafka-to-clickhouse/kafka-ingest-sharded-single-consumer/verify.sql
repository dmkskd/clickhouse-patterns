-- Each event stored exactly once, spread across shards: 8000 physical = 8000
-- distinct. No N-x read (one consumer) and no N-x storage (no duplication) --
-- the price is that all ingestion flows through a single shard.
SELECT count() AS physical, uniqExact(id) AS distinct_ids
FROM demo.events_all;
