-- Source schema + seed. Exists before the connector snapshots (runs at DB init).
CREATE TABLE IF NOT EXISTS test.orders (
    id       INT PRIMARY KEY,
    customer VARCHAR(64),
    amount   INT
);
CREATE TABLE IF NOT EXISTS test.orders_existing (
    id       INT PRIMARY KEY,
    customer VARCHAR(64),
    amount   INT
);
INSERT INTO test.orders (id, customer, amount) VALUES
    (1, 'alice', 100),
    (2, 'bob',   200),
    (3, 'carol', 300);
INSERT INTO test.orders_existing (id, customer, amount) VALUES
    (1, 'alice', 100),
    (2, 'bob',   200),
    (3, 'carol', 300);
