-- All three options read the same live Postgres rows. No FINAL, no
-- version column, no tombstones: the deleted row is simply gone, because
-- ClickHouse is reporting what Postgres currently holds.
SELECT access_path, id, customer, amount
FROM
(
    SELECT 1 AS path_order, 'TABLE ENGINE' AS access_path, id, customer, amount
    FROM test.orders_table_engine

    UNION ALL

    SELECT 2, 'DATABASE ENGINE', id, customer, amount
    FROM pg_schema.orders

    UNION ALL

    SELECT 3, 'TABLE FUNCTION', id, customer, amount
    FROM postgresql('postgres:5432', 'test', 'orders', 'postgres', 'postgres')
)
ORDER BY path_order, id;
