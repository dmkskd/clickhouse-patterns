-- Source schema + seed (runs at Postgres init against POSTGRES_DB=test).
CREATE TABLE IF NOT EXISTS orders (
    id       INT PRIMARY KEY,
    customer VARCHAR(64),
    amount   INT
);
CREATE TABLE IF NOT EXISTS orders_existing (
    id       INT PRIMARY KEY,
    customer VARCHAR(64),
    amount   INT
);
INSERT INTO orders (id, customer, amount) VALUES
    (1, 'alice', 100),
    (2, 'bob',   200),
    (3, 'carol', 300);
INSERT INTO orders_existing (id, customer, amount) VALUES
    (1, 'alice', 100),
    (2, 'bob',   200),
    (3, 'carol', 300);
