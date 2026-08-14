# Offline backfill with BACKUP and RESTORE via S3

Profiles: `single`, `s3`. Driver: `ch`.

For a one-off, high-volume load (a historical import or backfill), parsing rows over
an INSERT stream is the expensive part. This pattern builds the parts offline and
moves them into the cluster through S3: a worker runs
[`BACKUP TABLE ... TO S3`](https://clickhouse.com/docs/operations/backup), and the
a client runs `RESTORE TABLE ... FROM S3` against the target ClickHouse cluster,
using the same location. Nothing is
re-parsed, and neither side needs filesystem access to the other.

There is no dedicated bulk-import feature at work here. The pattern is a composition
of primitives already available, an offline worker, object storage, and
BACKUP/RESTORE, arranged for one job. It is meant as an example of thinking in
primitives, since the same pieces recombine into other loaders and this is one
useful arrangement rather than the only one. It is marked experimental for that reason.

```
clickhouse-local worker --BACKUP TO S3--> S3: backups/events-backfill
                                                |
                                    RESTORE FROM S3 (no INSERT stream)
                                                v
                                          demo.events
```

## Why through S3 rather than attaching parts

Whole MergeTree parts can also be moved by copying them into a table's `detached/`
directory and running `ATTACH PARTITION`, but that needs filesystem access to the
cluster, which ClickHouse Cloud does not grant. `RESTORE FROM S3` pulls the same
parts through object storage instead, with no filesystem access, so it also loads
into Cloud. This is the documented path for
[migrating a self-managed table into ClickHouse Cloud](https://clickhouse.com/docs/cloud/migration/oss-to-cloud-backup-restore).
The parts are packaged, not streamed, so the target skips the parse and compress
step an INSERT would pay, and ClickHouse verifies each part's checksum as it
restores.

On Cloud the restore differs in two ways. It authenticates with role-based
credentials (`extra_credentials(role_arn = '...')`) rather than inline keys, and
`MergeTree` tables come back as `SharedMergeTree`. The worker that writes the
backup runs off the cluster (clickhouse-local or a self-managed instance), so only
the restore side touches Cloud.

## Data files vs prebuilt parts

The other patterns in this group also read from S3, but they move different things:

- `s3()` and `S3Queue()` read **data files** (Parquet, CSV, JSONEachRow) that any
  producer can write, and **parse every row** into the target through the normal
  insert path. Schema is a mapping from file columns to table columns. They differ
  from each other only in the trigger. `s3()` is a pull that is run or scheduled;
  `S3Queue()` is a continuous loop that processes each new file exactly once.
- `BACKUP`/`RESTORE` moves **prebuilt MergeTree parts** packaged as a
  ClickHouse-native backup, which only ClickHouse or clickhouse-local can produce.
  `RESTORE` unpacks the parts as-is: **no row parsing**, and both sides must share
  the same table structure.

So `s3()` and `S3Queue()` bring in data to be parsed (any format, ongoing or
repeatable); this pattern relocates an already-built dataset (ClickHouse format,
one-off).

## What the load does

`load.py` runs both sides against one node to stay self-contained. The worker side
builds 3000 rows, then consolidates them before export:

```sql
OPTIMIZE TABLE demo.events_staging FINAL;
BACKUP TABLE demo.events_staging TO S3('.../backups/events-backfill', ...);
```

`OPTIMIZE FINAL` collapses the data into one part so the restore lands few, large
parts rather than many small ones. The cluster side restores under a new name:

```sql
RESTORE TABLE demo.events_staging AS demo.events FROM S3('.../backups/events-backfill', ...);
```

`demo.events` ends with 3000 rows, restored from S3 with no INSERT stream.

## Handling a large restore

A restore that lands many small parts can hit too-many-parts pressure. Consolidate
with `OPTIMIZE FINAL` before the backup, and for a large restore consider
`SYSTEM STOP MERGES` on the target during the load and resuming after. Both sides
need the same table structure. `BACKUP`/`RESTORE` can also scope to partitions
(`BACKUP TABLE t PARTITIONS '2023-01' TO S3(...)`) for a targeted backfill.

## When to choose it

A one-off historical or backfill load where re-parsing rows would dominate, and the
target may be on ClickHouse Cloud. For an evolving or streaming source use the
[s3() bulk load](../s3-bulk-load/) or [S3Queue](../s3queue-ordered/) instead; this
is a bulk operation, not a continuous loader.

```bash
just test s3-backup-restore
```

## Reference

- [ClickHouse: Backup and Restore](https://clickhouse.com/docs/operations/backup)
- [ALTER TABLE ... REPLACE/ATTACH PARTITION](https://clickhouse.com/docs/sql-reference/statements/alter/partition)
  (the filesystem alternative, self-hosted only)
