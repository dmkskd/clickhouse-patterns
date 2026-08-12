-- The transition events read back from the alerts topic, in order.
-- checkout fires, then resolves; health never appears.
SELECT service, type
FROM demo.alerts_events
ORDER BY at, service;
