-- The same two events for customer 1, read both ways.
--   STORED    the tier resolved at insert time and written to the fact row
--   CURRENT   the tier resolved per read, from the dictionary as it stands now
-- Event 1 arrived before the promotion and event 4 after it, so STORED differs
-- between them while CURRENT does not.
SELECT reading, event_id, customer_name, customer_tier, toString(amount) AS amount
FROM
(
    SELECT 1 AS reading_order, 'STORED (dictGet at insert)' AS reading,
           event_id, customer_name, customer_tier, amount
    FROM test.events_enriched
    WHERE customer_id = 1

    UNION ALL

    SELECT 2, 'CURRENT (dictGet at read)',
           event_id, customer_name, customer_tier, amount
    FROM test.events_current_tier
    WHERE customer_id = 1
)
ORDER BY reading_order, event_id;
