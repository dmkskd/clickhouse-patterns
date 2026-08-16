CREATE DATABASE IF NOT EXISTS demo;

-- The table starts on a five-year retention policy, the kind of period a
-- compliance or audit requirement usually sets, so none of the history it
-- holds is expired yet. Partitioning by event month is what later makes a
-- partial, month-by-month rollout of a shorter policy possible.
CREATE TABLE demo.events
(
    event_time DateTime,
    id UInt64,
    payload String
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (event_time, id)
TTL event_time + INTERVAL 5 YEAR DELETE;

-- The retention change itself is an operation, not a schema definition, so it
-- lives in the loader: the table is populated first, and only then does the
-- policy change from 100 years to 30 days.
