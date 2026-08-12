CREATE DATABASE IF NOT EXISTS demo;

-- A bulk import appends rows into a plain MergeTree. The s3() table function
-- reads one file, or many at once through a glob in the path, in a single INSERT.
-- There is no deduplication or file tracking, so re-running the load appends the
-- same rows again.
CREATE TABLE demo.events
(
    id   UInt64,
    kind String
)
ENGINE = MergeTree
ORDER BY id;
