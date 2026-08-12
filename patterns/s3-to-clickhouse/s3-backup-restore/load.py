"""Offline backfill through S3: BACKUP a table to S3, then RESTORE it into the cluster.

A worker (clickhouse-local, or any ClickHouse instance) builds parts off the serving
cluster and backs them up to S3. The cluster restores from the same S3 location. The
rows travel as packaged parts, so the target does not re-parse them over an INSERT
stream, and no filesystem access to the cluster is needed, so this also works on
ClickHouse Cloud.
"""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")

# One S3 location, written by the backup and read by the restore. MinIO stands in
# for S3; the backups bucket is created when the stack starts.
BACKUP = "S3('http://minio:9000/backups/events-backfill', 'clickhouse', 'clickhouse_secret')"

# Worker side: build 3000 rows, then consolidate into as few parts as possible.
# Fewer, larger parts mean less merge pressure when the cluster restores them.
ch.command(
    "INSERT INTO demo.events_staging "
    "SELECT number AS id, ['click', 'view', 'purchase'][number % 3 + 1] AS kind FROM numbers(3000)"
)
ch.command("OPTIMIZE TABLE demo.events_staging FINAL")
ch.command(f"BACKUP TABLE demo.events_staging TO {BACKUP}")
print("worker: built 3000 rows, optimized to one part, backed up to S3")

# Cluster side: restore the parts from S3 into the serving table under a new name.
# There is no INSERT stream and no row re-parsing; the parts are unpacked from the
# backup, and ClickHouse checks each part's checksum as it restores.
ch.command(f"RESTORE TABLE demo.events_staging AS demo.events FROM {BACKUP}")
print("cluster: restored parts from S3 into demo.events")
