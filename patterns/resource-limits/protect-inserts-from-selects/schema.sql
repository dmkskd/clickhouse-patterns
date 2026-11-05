CREATE DATABASE demo;

CREATE TABLE demo.events
(
    run_id UUID,
    batch UInt32,
    id UInt32,
    value UInt64
)
ENGINE = MergeTree
ORDER BY (run_id, batch, id);

CREATE USER traffic_reader IDENTIFIED WITH no_password;
CREATE USER traffic_writer IDENTIFIED WITH no_password;
GRANT SELECT ON demo.* TO traffic_reader;
GRANT INSERT ON demo.events TO traffic_writer;
ALTER USER traffic_reader SETTINGS
    max_concurrent_queries_for_user = 2 CONST,
    max_threads = 1 CONST,
    max_execution_time = 5 CONST,
    max_memory_usage = 134217728 CONST,
    log_queries = 1 CONST;
ALTER USER traffic_writer SETTINGS
    async_insert = 0 CONST,
    max_execution_time = 5 CONST,
    log_queries = 1 CONST;
