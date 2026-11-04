-- Pattern-local source write timestamps, populated before the snapshot.
ALTER TABLE test.orders
    ADD COLUMN created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ADD COLUMN updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6);
TRUNCATE TABLE test.orders;
INSERT INTO test.orders (id, customer, amount) VALUES
    (1, 'alice', 100), (2, 'bob', 200), (3, 'carol', 300);
ALTER TABLE test.orders_existing
    ADD COLUMN created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    ADD COLUMN updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6);
TRUNCATE TABLE test.orders_existing;
INSERT INTO test.orders_existing (id, customer, amount) VALUES
    (1, 'alice', 100), (2, 'bob', 200), (3, 'carol', 300);
