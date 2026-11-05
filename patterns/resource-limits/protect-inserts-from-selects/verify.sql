SELECT item, value FROM (
SELECT 'seed' AS item, concat(toString(count()), '/', toString(sum(value))) AS value
FROM demo.events WHERE run_id = toUUID('00000000-0000-0000-0000-000000000000')
UNION ALL
SELECT name AS item, storage AS value FROM system.users
WHERE name IN ('traffic_reader', 'traffic_writer')
)
ORDER BY item;
