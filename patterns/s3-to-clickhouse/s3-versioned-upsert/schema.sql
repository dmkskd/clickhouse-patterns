CREATE DATABASE IF NOT EXISTS demo;

-- Keyed target for versioned upserts. Each row carries a `version` number, higher
-- for newer data (here a per-batch sequence; PeerDB uses a nanosecond sync time).
-- ReplacingMergeTree(version) keeps the highest version per ORDER BY key, so a
-- later correction wins and re-loading an older batch cannot overwrite it. Read
-- with FINAL to collapse to the latest version per key. Requires a stable key.
CREATE TABLE demo.events
(
    id      UInt64,
    kind    String,
    version UInt64
)
ENGINE = ReplacingMergeTree(version)
ORDER BY id;
