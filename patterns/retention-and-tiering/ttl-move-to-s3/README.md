# TTL move to an S3 volume

This runnable pattern keeps current data on the `default` local disk and moves
parts whose `event_time` is older than 30 days to `cold_s3`, an S3 disk backed
by the stack's MinIO service.

`config/tiered-storage.xml` is mounted only for this pattern through
`spec.services.clickhouse.config` in `pattern.yaml`. It adds the `cold_s3` disk and `tiered`
storage policy under ClickHouse `config.d`; it does not replace the shared
server configuration. The table opts into that policy in `schema.sql`.

## What a cross-tier move does

For a move to another disk or volume, ClickHouse first clones the selected part
onto the destination. After the destination part has been built and checked,
ClickHouse switches it into the active part set and marks the source part
inactive. Reads immediately use the destination because `system.parts.active`
has switched to it.

The inactive source is a safety copy, not a second active copy. It is retained
for at least `old_parts_lifetime` (480 seconds by default), then the cleanup
task removes it once no query holds a reference. The elapsed time can therefore
be longer than eight minutes. On an S3 source tier, that later cleanup is when
the source objects are deleted.

Observe both states while the source remains available:

```sql
SELECT name, active, disk_name, rows, remove_time
FROM system.parts
WHERE database = 'demo' AND table = 'tiered_events'
ORDER BY name, active DESC, disk_name;
```

After the switch, the moved part appears with `active = 1` on `cold_s3`; its
former `default`-disk copy appears with `active = 0` until cleanup. Use
`system.part_log` to see the `MOVE_PART` event.

The load inserts two rows in an expired monthly partition and two current rows.
The cold volume has `perform_ttl_move_on_insert = 0`, so an already-expired
insert initially lands locally. `ALTER TABLE ... MATERIALIZE TTL` then makes
the demonstration deterministic. The checks require one active part on
`cold_s3`, one on `default`, and the expected two rows on each.

MOVE TTL has its own per-table `Moving` scheduler in
`background_schedule_pool`. It scans active parts, compares each part's stored
MOVE-TTL maximum with the current time, and submits eligible parts to the move
executor (`background_move_pool_size`). Empty scans use exponential back-off;
the `background_move_processing_pool_*` settings control it. Monitor
`system.parts`, `system.part_log`, and `system.moves`. Use environment- or
secret-backed credentials instead of the development MinIO credentials in this
example.
