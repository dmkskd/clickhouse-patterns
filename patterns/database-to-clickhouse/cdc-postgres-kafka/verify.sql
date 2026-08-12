-- Current state, with the Kafka coordinates each row arrived on. FINAL keeps
-- the highest __lsn per id, and the rewritten delete event is filtered rather
-- than removed, so the table still records that the row was deleted.
--
-- __offset and __timestamp are real but vary per run, so they are checked for
-- presence rather than value.
SELECT
    id,
    customer,
    amount,
    __topic,
    __partition,
    __offset >= 0        AS has_offset,
    __timestamp > 0      AS has_timestamp
FROM test.orders FINAL
WHERE __deleted = 'false'
ORDER BY id;
