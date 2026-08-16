CREATE DATABASE IF NOT EXISTS demo;

-- The table starts on a one-year retention policy. Partitioning by event month
-- is what later makes a partial, month-by-month rollout of a shorter policy
-- possible.
CREATE TABLE demo.events
(
    event_time DateTime,
    id UInt64,
    payload String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, id)
TTL event_time + INTERVAL 1 YEAR DELETE;

-- The retention change itself is an operation rather than a schema definition,
-- so it lives in the loader: the table is populated first, and only then does
-- the policy change from one year to 30 days.
