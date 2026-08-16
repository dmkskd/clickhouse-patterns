SELECT
    if(max_time < now() - INTERVAL 30 DAY, 'expired', 'current') AS age,
    disk_name,
    sum(rows) AS rows
FROM system.parts
WHERE database = 'demo' AND table = 'tiered_events' AND active
GROUP BY age, disk_name
ORDER BY age;
