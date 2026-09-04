-- One row per active part: where it lives, whether its TTL has expired,
-- and what system.part_log recorded for its partition (moves vs merges).

SELECT
    -- The current month's partition id changes on every run, so mask it to a
    -- stable label. '200001' is fixed: the load inserts old rows dated 2000-01.
    if(p.partition = '200001', p.partition, 'current month') AS partition_label,

    p.rows,
    p.disk_name,

    -- max_time is the newest event_time in the part. A part can move only
    -- when even its newest row is older than the 30-day TTL.
    if(p.max_time < now() - INTERVAL 30 DAY, 'eligible', 'waiting for newest row') AS ttl_state,

    -- The point of the demo: the expired part was moved whole (one MovePart
    -- event, zero MergeParts), while the hot partition lived normally (zero
    -- MovePart, one MergeParts consolidating the two load inserts).
    ifNull(l.moves, 0) AS move_events,
    ifNull(l.merges, 0) AS merge_events

FROM system.parts AS p

LEFT JOIN
(
    -- part_log history for this table, pre-aggregated per partition
    SELECT
        partition_id,
        countIf(event_type = 'MovePart') AS moves,
        countIf(event_type = 'MergeParts') AS merges
    FROM system.part_log
    WHERE database = 'demo' AND table = 'tiered_events'
    GROUP BY partition_id
) AS l ON l.partition_id = p.partition

WHERE p.database = 'demo' AND p.table = 'tiered_events' AND p.active
ORDER BY p.min_time;
