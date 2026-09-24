-- Pattern-owned Postgres seed, mounted into /docker-entrypoint-initdb.d and run
-- at container init after the stack's shared init.sql. This is the dimension the
-- dictionary reads; the facts are inserted into ClickHouse directly.
CREATE TABLE IF NOT EXISTS customers (
    id   INT PRIMARY KEY,
    name VARCHAR(64),
    tier VARCHAR(16)
);
INSERT INTO customers (id, name, tier) VALUES
    (1, 'acme',   'gold'),
    (2, 'globex', 'silver'),
    (3, 'initech', 'bronze');
