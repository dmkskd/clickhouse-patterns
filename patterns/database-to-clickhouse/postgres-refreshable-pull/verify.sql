-- Three reads of the same source, side by side.
--   CURRENT   the full-replace MV: one row per key, always the newest state
--   LATEST    the newest snapshot read back out of the append-only history
--   HISTORY   proof the history kept a row that Postgres no longer has
SELECT scenario, id, customer, amount, amount_band
FROM
(
    SELECT 1 AS scenario_order, 'CURRENT (full replace)' AS scenario,
           id, customer, toString(amount) AS amount, amount_band
    FROM test.orders

    UNION ALL

    SELECT 2, 'LATEST (from history)', id, customer, toString(amount), amount_band
    FROM test.orders_latest

    UNION ALL

    SELECT 3, 'HISTORY (deleted in Postgres)', id, customer, toString(amount), amount_band
    FROM (SELECT DISTINCT id, customer, amount, amount_band FROM test.orders_history WHERE id = 3)
)
ORDER BY scenario_order, id;
