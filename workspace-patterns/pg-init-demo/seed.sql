-- Pattern-owned Postgres seed. The compose overlay mounts this file into
-- /docker-entrypoint-initdb.d as zz-pattern-seed.sql, so it runs at container
-- init, after the stack's shared init.sql.
CREATE TABLE IF NOT EXISTS customers (
    id   INT PRIMARY KEY,
    name VARCHAR(64)
);
INSERT INTO customers (id, name) VALUES
    (1, 'acme'),
    (2, 'globex');
