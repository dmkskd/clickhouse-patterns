-- Each event stored on exactly one shard: 4000 + 4000, no overlap.
-- `_shard_num` is the Distributed engine's shard virtual column.
SELECT _shard_num AS shard, count() AS rows
FROM demo.events_all
GROUP BY shard
ORDER BY shard;
