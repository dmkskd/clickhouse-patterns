-- Services currently in an alert state. Only the breaching service (checkout)
-- should be present; the refreshable MV re-emits it every 5s and the
-- ReplacingMergeTree collapses those to one row.
SELECT service
FROM demo.alerts_store FINAL
ORDER BY service;
