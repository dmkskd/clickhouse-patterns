-- Current state, with the Kafka coordinates each row arrived on. FINAL keeps
-- the highest __lsn per id, and the rewritten delete event is filtered rather
-- than removed, so the table still records that the row was deleted.
--
-- __offset and __timestamp are real but vary per run, so they are checked for
-- presence and plausibility rather than value: a timestamp written in the wrong
-- unit lands centuries away from now().
SELECT
    id,
    customer,
    amount,
    __topic,
    __partition,
    __offset >= 0        AS has_offset,
    abs(dateDiff('hour', __timestamp, now64(3))) < 24 AS has_timestamp
FROM test.orders FINAL
WHERE __deleted = 'false'
ORDER BY id;
