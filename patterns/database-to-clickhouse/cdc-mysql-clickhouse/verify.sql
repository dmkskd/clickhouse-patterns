-- Reads the final state of all three targets. Against the loader's mutations
-- (INSERT id=4, UPDATE id=2 -> 250, DELETE id=3), the expected output proves:
--   the insert and update landed in every table (dave 400, bob 250),
--   the delete propagated to every table (no id=3 row), and
--   the update flowed through the materialized view: bob's band is 'high',
--   which only the new amount (250 >= 250) produces.
-- FINAL + is_deleted = 0 is the current-state read this pattern requires.
SELECT scenario, id, customer, amount, amount_band
FROM
(
    SELECT 1 AS scenario_order, 'CDC-CREATED TABLE' AS scenario,
           id, customer, toString(amount) AS amount, '-' AS amount_band
    FROM test.orders FINAL
    WHERE is_deleted = 0

    UNION ALL

    SELECT 2, 'TRANSFORMATION', id, customer, toString(amount), toString(amount_band)
    FROM test.orders_transformed FINAL
    WHERE is_deleted = 0

    UNION ALL

    SELECT 3, 'EXISTING TARGET TABLE', id, customer, toString(amount), toString(amount_band)
    FROM test.orders_existing FINAL
    WHERE is_deleted = 0
)
ORDER BY scenario_order, id;
