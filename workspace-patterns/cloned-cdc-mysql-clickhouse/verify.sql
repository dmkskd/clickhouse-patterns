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
