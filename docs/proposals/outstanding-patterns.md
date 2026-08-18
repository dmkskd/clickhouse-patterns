# Outstanding patterns

Backlog of patterns to build, with background and design notes. Each entry lists
what it demonstrates, the infra it needs (Compose profiles), a rough sketch, and
references. See [../pattern-explorer.md](../pattern-explorer.md) for how patterns are structured.

Status audit: entries stay in this document after implementation and receive an
`Implemented` status with a link to `../../patterns/<group>/<slug>/`. A `Related` link
means useful coverage exists, but the proposed mechanism itself remains
outstanding. Entries without either status still need an explicit audit.

Status of the infra: profiles now cover `single`, `cluster`, `shards`,
`shards-v2` (ClickHouse nightly for StorageKafka2), `s3queue` (a Keeper-backed
node paired with MinIO), `cdc-ch` (pinned 25.3 for the Altinity sink), `mysql`,
`cdc-mysql`, `postgres`, `cdc-postgres`, `peerdb`, `s3` (MinIO), `kafka`, and
`connect`. Object storage as an ingestion buffer is now covered for the S3Queue
mechanism (`s3queue-ordered`, `s3queue-unordered`); an OpenData-style
producer/consumer runtime still does not exist. A `clickhouse-local` worker
exists in
[s3-backup-restore](../../patterns/s3-to-clickhouse/s3-backup-restore/). Some
proposals also need a two-node pair; those requirements are listed in their
`Infra` sections.

Harness and tooling proposals (not patterns):

- [measuring-metrics.md](measuring-metrics.md): **Outstanding.** Add assertions
  for operational metrics such as TTL merge cost and bytes moved. The TTL
  proposal depends on this capability.
- [patterns-as-skills.md](patterns-as-skills.md): **Partially implemented.**
  The shared
  [clickhouse-pattern-lab](../../skills/clickhouse-pattern-lab/SKILL.md) skill
  and Codex/Claude adapters operate runnable patterns. The proposed generated,
  domain-specific rule skills remain outstanding.
- [fault-recovery-scenarios.md](fault-recovery-scenarios.md): **Outstanding.**
  Fault injection mid-ingest and tested, topology-specific recovery procedures.
  The recovery claims already present in pattern `tradeoffs` blocks are the
  first candidates.

## Working taxonomy for movement and transformation

The proposals cover several movement and transformation problems with different
correctness boundaries. They are classified by the problem being addressed;
Kafka, dbt, PeerDB, materialized views, and object storage remain possible
implementation mechanisms.

- **CDC:** how inserts, updates, and deletes leave a mutable source and reach a
  source-faithful ClickHouse landing table.
- **Modeling and enrichment:** what query-facing shape should be built from the
  landed data, including joins, denormalization, derived columns, and
  aggregates.
- **Change propagation:** how a derived model is repaired when any input row is
  updated or deleted. This may be a cross-cutting concern rather than a final
  top-level category.
- **Ingestion correctness:** how duplicates, retries, late versions, event-time
  disorder, and file-arrival disorder are interpreted.
- **Buffering and decoupling:** how producers continue while ClickHouse is
  unavailable or slow, and how replay and backpressure are represented.

The design notes or tags can also record these properties without making them
required manifest fields:

- Execution: query-time, insert-triggered, scheduled recomputation, or stateful
  stream processing.
- State semantics: append-only events, latest current state, point-in-time
  ("as-was") state, or event-time windows.
- Transport: direct, durable log (Kafka), or object/file buffer (S3).

A pattern may cover more than one concern. Assign it one primary question and
record the other applicable properties. Revisit the manifest taxonomy after
runnable examples establish which properties are useful in `just list`.

## Ingestion throughput

### external-presorted-native-ingest

Status. **Outstanding.**
A `clickhouse-local` worker component now exists in
[s3-backup-restore](../../patterns/s3-to-clickhouse/s3-backup-restore/) and can
serve as the starting point for this pattern's worker.

Background. A high-rate source can make the destination ClickHouse spend CPU on
parsing, batching, and sorting rows while it is also serving queries and merging
parts. The proposed experiment delegates the first three jobs to a bounded
external worker. The worker collects a short micro-batch (for example five
seconds), applies transformations, sorts it by the exact destination sorting
key, and sends the result to the main ClickHouse as a Native-format stream.

This is logical row transfer, not physical part transfer:

```text
raw events
  -> external clickhouse-local/chDB worker
  -> transform and batch
  -> ORDER BY the exact destination sorting key
  -> FORMAT Native
  -> clickhouse-client / native TCP protocol
  -> main ClickHouse creates one or more level-0 MergeTree parts
```

Terminology. `Native` is ClickHouse's binary columnar data format. The native
TCP protocol is the client/server transport (normally port 9000). A MergeTree
part is a separate on-disk representation containing marks, indexes, codecs,
and metadata. A Native stream does not transfer a completed MergeTree part: the
destination still receives and decompresses blocks, creates its sparse index,
applies destination codecs, and writes a new part. Presorting aims to remove or
simplify the destination's sort step, not its entire insert path.

Primary question. Does moving micro-batch parsing and sorting off the main
server reduce destination insert CPU and improve compression enough to justify
the worker's CPU, memory, disk, latency, and operational cost? Presorting does
not by itself remove the need to merge parts later. Batching may reduce part
creation only when it replaces smaller inserts with fewer larger inserts.
ClickHouse documents presorting as an optional optimisation, not a universal
recommendation, so this needs a measured comparison rather than an example that
only proves row correctness.

Demonstrates. Insert the same intentionally unordered batch into identical
destination tables through three paths:

1. Baseline: unordered rows -> `FORMAT Native` -> main ClickHouse.
2. External sort: rows -> `clickhouse-local` -> explicit destination-key
   `ORDER BY` -> `FORMAT Native` -> main ClickHouse.
3. Local MergeTree candidate: rows -> bounded local MergeTree -> optional local
   `OPTIMIZE ... FINAL` -> explicit destination-key `ORDER BY` ->
   `FORMAT Native` -> main ClickHouse.

The explicit final `ORDER BY` is the ordering contract. A local MergeTree or a
bounded `OPTIMIZE ... FINAL` is only an implementation candidate: neither should
be assumed necessary, and `OPTIMIZE ... FINAL` should not become a routine
operation on the main cluster. Compare the third path both with and without the
local optimisation to determine whether it saves work or only adds local I/O.

Validation. All paths use the same source rows, target DDL, batch boundaries,
and Native handoff. Assert equal row counts and checksums, then measure:

- end-to-end rows per second and insert latency;
- destination CPU and elapsed insert time;
- worker CPU, memory, temporary disk, and elapsed time;
- destination parts created and subsequent merge work; and
- compressed bytes sent over the network.

Start with a synthetic source so Kafka consumption does not obscure the cost
being measured. Add a Kafka-backed variant only after the isolated experiment
shows a material benefit.

Infra. `single` plus a new bounded worker using the same ClickHouse binary in
local mode. A persistent local MergeTree may require a worker data path or a
small worker server; choose between `clickhouse-local` and chDB only after the
stateless external-sort path is measured.

Related implementation, not proof of the full pattern. PostHog's Snuffle import
script reads Parquet with `clickhouse-local`, performs grouping and joins, emits
`FORMAT Native`, and pipes that into `clickhouse-client` for insertion. It proves
the local-transformation and Native-handoff mechanism. It does not create a
local MergeTree, run `OPTIMIZE`, or `ORDER BY` the destination sorting key, so
the destination still has to handle ordering for that workload.

Research note. A June 18, 2026 Altinity/Open Source Analytics Community meetup
in San Francisco included a PostHog presentation and may be the source of the
original idea, but no public title, slides, or recording currently document this
specific technique. Do not cite the meetup as technical evidence unless that
material becomes available.

References.
[Selecting an insert strategy](https://clickhouse.com/docs/best-practices/selecting-an-insert-strategy),
[ClickHouse Native format](https://clickhouse.com/resources/engineering/read-clickhouse-native-file),
[PostHog Snuffle Native import script](https://github.com/PostHog/snuffle/blob/main/scripts/ingest_metrics_parquet.sh),
[June 2026 Altinity/OSA meetup](https://luma.com/q3jx5f55).

### sync-distributed-insert-mv-local-target

Status. **Outstanding.** Related: the
[kafka-ingest-sharded-*](../../patterns/kafka-to-clickhouse/) patterns solve
first-hop partition-to-shard mapping; none of them exercise synchronous
`Distributed` inserts or a second-hop materialized view's write target.

Background. From an Altinity field report: a Kafka to ClickHouse pipeline on a
two-shard, two-replica cluster had ingestion lag stuck around 8.6 seconds with a
healthy cluster and idle CPU. The cluster deliberately ran synchronous
distributed inserts (`distributed_foreground_insert = 1`) because asynchronous
mode's spool files outgrew the shared background sender pool
(`background_distributed_schedule_pool_size`, shared across all `Distributed`
tables on the server) and ran away to roughly 525K files and tens of GiB. The
cost of that stability was a fixed cross-shard round-trip per insert: each hot
materialized view writing to a `Distributed` table spent about 3.3 seconds per
execution, almost all network wait (`net_ms` close to or above `wall_ms`,
`cpu_ms` near zero), flat across a 60x throughput range — the signature of a
fixed per-insert cost, not a row-processing problem. Repointing the second-hop
(enrichment) view from the `Distributed` wrapper to its `_local`
`ReplicatedMergeTree` table removed the second synchronous fan-out and halved
end-to-end lag (8.13 s to 3.87 s average; p95/p99 roughly halved), while
replication still handled durability.

Boundary condition. Writing to `_local` keeps rows on the consuming node
instead of routing them by the `Distributed` sharding key. This is safe only
when placement is distribution-oriented — the blog's target was sharded by
`cityHash64` on a high-cardinality id. Tables sharded by tenant or another
locality-sensitive key, and `ReplacingMergeTree` targets whose dedup scope
depends on the sharding key, need a redesign rather than this optimization.

Demonstrates. A two-hop chain on a sharded, replicated cluster with
`distributed_foreground_insert = 1`: a Kafka-engine consumer MV lands rows in a
`Distributed` table (first fan-out), and an enrichment MV reads the local table
and writes onward. Run the second hop twice — once targeting the `Distributed`
wrapper, once targeting `_local` — and show the network wait disappearing from
`system.query_views_log` for the changed view while row counts stay equal. Also
show that the remaining first-hop round-trip becomes the bottleneck afterwards,
so readers do not expect the cost to vanish entirely.

Measurement. `system.query_views_log` per-view breakdown of `view_duration_ms`
versus `ProfileEvents['NetworkReceiveElapsedMicroseconds']` and
`ProfileEvents['OSCPUVirtualTimeMicroseconds']` (via
`clusterAllReplicas('{cluster}', ...)`), plus an end-to-end lag KPI from a
source timestamp and a `DEFAULT now()` ingest timestamp. The per-view query
from the report doubles as the pattern's diagnostic: `net_ms` ≥ `wall_ms` with
`cpu_ms` ≈ 0 identifies a view that is waiting, not working. See
[measuring-metrics.md](measuring-metrics.md).

Infra. `shards` + `kafka`. The sync-insert setting goes in a per-pattern
`clickhouse_config` users.d fragment so it does not affect other patterns.

References.
[Pipeline optimization for ClickHouse distributed tables with synchronous inserts (Altinity)](https://altinity.com/blog/pipeline-optimization-for-clickhouse-distributed-tables-with-synchronous-inserts),
[Distributed engine](https://clickhouse.com/docs/engines/table-engines/special/distributed),
[query_views_log](https://clickhouse.com/docs/operations/system-tables/query_views_log).

## Backups and copies

### backup-restore-s3

Status. **Implemented** in
[s3-backup-restore](../../patterns/s3-to-clickhouse/s3-backup-restore/), which
performs the offline pre-processing with a `clickhouse-local` worker before
`BACKUP ... TO S3` and `RESTORE ... FROM S3`.

Background. The source Slack discussion recommended `BACKUP` to S3 followed by
`RESTORE` from S3 for moving data between clusters. This method does not require
filesystem access and is available on ClickHouse Cloud. Backups can target
specific partitions.

Demonstrates. `BACKUP TABLE ... TO S3(...)` then `RESTORE TABLE ... FROM S3(...)`,
including `SETTINGS allow_non_empty_tables=1` and `PARTITIONS '...'`. The test
asserts row counts and a checksum match between source and restored table.

Infra. `single` + `s3` can show the mechanism by restoring a table into a second
database on the same node. Testing transfer between servers needs a new `pair`
profile with independent `ch-a` and `ch-b` nodes.

Sketch.
```sql
BACKUP TABLE src.events TO S3('http://minio:9000/backups/events', 'key', 'secret');
RESTORE TABLE src.events AS dst.events
  FROM S3('http://minio:9000/backups/events', 'key', 'secret')
  SETTINGS allow_non_empty_tables=1;
```

References. [ClickHouse backup docs](https://clickhouse.com/docs/operations/backup).

### offline-parts-backup

Status. **Implemented (mechanism)** in
[s3-backup-restore](../../patterns/s3-to-clickhouse/s3-backup-restore/): an
isolated worker builds data offline, backs it up to S3, and the target restores
it. The implementation uses `clickhouse-local` for the worker rather than the
small ClickHouse server this proposal recommended, so that open question is
resolved in favor of `clickhouse-local`. The comparison with `REPLACE
PARTITION` from staging remains outstanding under
[replace-partition-staging](#replace-partition-staging).

Background. The original Slack question also asked about moving large batches
as physical ClickHouse data rather than streaming logical rows through an
`INSERT`. This is a separate problem from
`external-presorted-native-ingest`. Its supported boundary is ClickHouse backup,
restore, and partition operations: build data in an isolated ClickHouse with a
compatible schema, back it up to object storage, then restore it into the target.
This is intended for historical backfills and bulk movement, not five-second
streaming micro-batches.

Demonstrates. An isolated ClickHouse worker builds a bounded table or partition,
optionally consolidates it locally when measurement justifies doing so, backs it
up to S3, and the target restores it. The test asserts row counts and checksums,
schema compatibility, and the resulting target partitions/parts. It must not use
`SYSTEM STOP MERGES` as a general solution to "too many parts": stopping merges
prevents ClickHouse from reducing part count and can make that condition worse.

Open design questions. Confirm the supported version and topology constraints
for restoring into a non-empty target, replicated tables, and partition-scoped
backups. Compare backup/restore with `REPLACE PARTITION` from a staging table.
Do not describe `FORMAT Native` as physical part movement; Native contains typed
column blocks, while backup/restore preserves ClickHouse storage artifacts and
metadata through a different mechanism.

Infra. New isolated ClickHouse `worker` component + `s3` + a target (`cluster`
or `single`). Prefer a small ClickHouse server for the first implementation so
`BACKUP` behavior is explicit; evaluate `clickhouse-local` only after confirming
that its persistent-storage and backup behavior matches the supported workflow.

References. [Backup docs](https://clickhouse.com/docs/operations/backup),
[ALTER PARTITION](https://clickhouse.com/docs/sql-reference/statements/alter/partition).

### replace-partition-staging

Status. **Outstanding.**

Background. A partition backfill can load data into a staging table with the
same structure, then run `ALTER TABLE target REPLACE PARTITION ... FROM staging`.
The partition replacement is atomic. Both tables must share the structure,
partition key, `ORDER BY`, and storage policy.

Demonstrates. Atomic partition replacement. The test loads a corrected partition
into staging, swaps it in, and asserts the target reflects the new data with no
intermediate inconsistent state.

Infra. `single`.

Sketch.
```sql
CREATE TABLE staging AS target;
INSERT INTO staging SELECT ... ;                       -- corrected data
ALTER TABLE target REPLACE PARTITION '2023-01' FROM staging;
```

References. [ALTER PARTITION](https://clickhouse.com/docs/sql-reference/statements/alter/partition).

### table-cloning

Status. **Outstanding.**

Background. `CREATE TABLE ... CLONE AS` creates a copy that initially shares the
source table's data parts without rewriting them. This can be used for snapshots
and development copies.

Demonstrates. Cloning a table, showing the clone shares parts with the source
initially and diverges only on new writes. The test asserts the clone has the
same rows and that writes to one do not affect the other.

Infra. `single`.

References. [Table cloning blog](https://clickhouse.com/blog/table-cloning).

### freeze-backup

Status. **Outstanding.**

Background. `ALTER TABLE ... FREEZE` creates a local hardlink snapshot of parts
under `shadow/`. Unlike `BACKUP` and `RESTORE`, it requires filesystem access.

Demonstrates. Freeze a partition, verify that the snapshot uses hardlinks, and
compare the workflow with an S3 backup. The pattern does not apply to ClickHouse
Cloud because it requires filesystem access.

Infra. `single`.

References. [ALTER FREEZE PARTITION](https://clickhouse.com/docs/sql-reference/statements/alter/partition#freeze-partition).

### attach-detach-parts

Status. **Outstanding.**

Background. `ALTER TABLE ... ATTACH/DETACH PARTITION` moves parts in and out via
the `detached/` directory. This provides a filesystem-based part-transfer
workflow and does not work on ClickHouse Cloud.

Demonstrates. Detaching a partition and re-attaching it, and attaching parts
placed in `detached/` by an external process.

Infra. `single` (with filesystem access to the part directory).

## Retention and tiered storage (TTL)

TTL has several actions, and they differ in cost:

- `DELETE` (and `RECOMPRESS`, `GROUP BY` rollup): rewrite the part. A row-level
  `DELETE WHERE` TTL re-reads and re-writes surviving rows to drop expired ones.
- `TO VOLUME` / `TO DISK` (move): relocate the whole part as a unit, no row-level
  rewrite. This is how cold data moves to cheaper storage (for example S3).

With `ttl_only_drop_parts = 1`, ClickHouse can drop a whole part once all its
rows have expired instead of rewriting it. Rows remain until the last row in the
part expires, and the setting is effective only when parts contain similar
expiration times. Delete and recompress TTL merges are paced by
`merge_with_ttl_timeout` (default 4h); moves are scheduled by a separate
background move task.

### ttl-delete-mixed-retention

Status. **Outstanding.**

Background. From a Slack thread: a monthly-partitioned events table where
different `event_type` values need different retention (2 months for click
events, 12 months for engagement, 2 years for transactions), all mixed in the
same monthly partition. Three approaches were discussed, with guidance from
ClickHouse.

- Option 1, row-level TTL `DELETE WHERE`: one `MODIFY TTL` with per-type
  intervals. A `DELETE WHERE` TTL rewrites the whole part when it runs,
  re-reading and re-writing all surviving rows to drop the expired ones. The
  same part may be rewritten repeatedly as data expires, so long-lived rows are
  processed while short-lived rows age out. If this approach is used, tune
  `merge_with_ttl_timeout` (default 4h) and evaluate `ttl_only_drop_parts`.
- Option 2, `retention_tier` in the partition key: a materialized `retention_tier`
  column added to `PARTITION BY (retention_tier, toYYYYMM(event_date))`, so each
  tier gets its own partitions and purging uses `DROP PARTITION` without
  rewriting surviving rows. Partition count is bounded in this example (3 tiers
  x 24 months = 72). The design adds schema and may scan all partitions when
  `event_type` is not in the index; a skip index or partition pruning can address
  that query pattern.
- Option 3, separate physical tables per tier, routed from Kafka via one MV per
  event-type group, each table with its own TTL. This isolates retention work by
  tier but requires reads across several tables.

Demonstrates. Compare the work performed by the three approaches while producing
the same retained rows. The measurements should show rows rewritten by the
row-level TTL and confirm that `DROP PARTITION` does not rewrite surviving rows.

Infra. `single` (plus `kafka` if Option 3's MV routing is shown end to end).

Measurement. Needs `system.part_log` (TTL merge `rows`/`bytes`), forced TTL
(`OPTIMIZE ... FINAL` or `ALTER TABLE ... MATERIALIZE TTL`) with event times in
the past, and `SYSTEM FLUSH LOGS` before reading. See
[measuring-metrics.md](measuring-metrics.md).

References.
[Manage data with TTL](https://clickhouse.com/docs/guides/developer/ttl),
[MergeTree settings](https://clickhouse.com/docs/operations/settings/merge-tree-settings)
(`ttl_only_drop_parts`, `merge_with_ttl_timeout`).

### ttl-move-to-s3

Status. **Outstanding.**

Background. A `TO VOLUME` or `TO DISK` TTL can keep recent data on local disk and
move older parts to object storage. Unlike `DELETE`, this relocates whole parts
instead of rewriting individual rows.

Demonstrates. A storage policy with a hot volume (local) and a cold volume (an S3
disk backed by MinIO), a `TTL ... TO VOLUME 'cold'` rule, and a forced move. The
test asserts that eligible parts now live on the S3 disk and hot parts stay local,
and measures that the move rewrote ~0 rows (whole-part relocation), in contrast to
a row-level DELETE.

Infra. `single` + `s3` (first user of the `s3` profile), with a
`storage_configuration` adding an S3 disk and a hot/cold policy.

Sketch.
```sql
-- storage policy 'tiered' with volumes: hot (local), cold (s3) in config
CREATE TABLE events (...) ENGINE = MergeTree ORDER BY ...
SETTINGS storage_policy = 'tiered';
ALTER TABLE events MODIFY TTL event_time + INTERVAL 1 MONTH TO VOLUME 'cold';
```

Measurement. `system.parts.disk_name` (where each part lives), `system.part_log`
`MovePart` events (bytes moved, ~0 rows rewritten). See
[measuring-metrics.md](measuring-metrics.md).

References.
[Manage data with TTL (moves)](https://clickhouse.com/docs/guides/developer/ttl),
[Separation of storage and compute / S3 disks](https://clickhouse.com/docs/guides/separation-storage-compute).

## CDC

### cdc-postgres-peerdb

Status. **Implemented** in
[cdc-postgres-peerdb](../../patterns/database-to-clickhouse/cdc-postgres-peerdb/). Related:
[cdc-mysql-clickhouse](../../patterns/database-to-clickhouse/cdc-mysql-clickhouse/) implements
the same Postgres mutations with the Altinity/Debezium sink for comparison.

Background. PeerDB is an open-source, Postgres-focused CDC engine acquired by
ClickHouse; it powers ClickPipes for Postgres. It is an alternative to the
Altinity/Debezium sink in
[cdc-mysql-clickhouse](../../patterns/database-to-clickhouse/cdc-mysql-clickhouse/), with a
different snapshot and replication implementation.

Demonstrates. Self-hosted PeerDB replicating the same Postgres source into
ClickHouse, so it can be compared directly against the Debezium version (snapshot
behaviour, resulting table shape, throughput).

Infra. `postgres` (reused) + `peerdb` + `s3` staging + a `single` ClickHouse
target. The local stack makes PeerDB's catalog, Temporal, API, snapshot worker,
and CDC worker explicit; ClickPipes manages those operational components.

References. [PeerDB quickstart](https://docs.peerdb.io/quickstart/quickstart),
[open-source Postgres and ClickHouse stack](https://clickhouse.com/blog/postgres-clickhouse-oss),
and [ClickPipes versus self-hosted PeerDB](https://clickhouse.com/blog/clickpipes-postgres-failover-replication).

## Streaming and alerting

### kafka-per-event-alert

Status. **Outstanding.** Related:
[kafka-produce-refreshable-mv](../../patterns/clickhouse-to-kafka/kafka-produce-refreshable-mv/) and
[kafka-produce-refreshable-mv-transitions](../../patterns/clickhouse-to-kafka/kafka-produce-refreshable-mv-transitions/)
implement timer-driven window alerts, not immediate per-event alerts.

Background. The event-driven counterpart to the refreshable-MV alert patterns. A
plain materialized view on the Kafka source emits immediately when a single event
crosses a hard threshold (for example one request over 5s), with no timer and no
windowing. This produces per-event alerts but cannot calculate windowed
statistics.

Demonstrates. Per-event push versus the interval push of
[../../patterns/clickhouse-to-kafka/kafka-produce-refreshable-mv](../../patterns/clickhouse-to-kafka/kafka-produce-refreshable-mv/),
side by side.

Infra. `single` + `kafka`.

### aggregating-mergetree-quantile-state

Status. **Outstanding.** Related:
[kafka-produce-refreshable-mv](../../patterns/clickhouse-to-kafka/kafka-produce-refreshable-mv/)
computes p90 from retained raw samples; it does not persist
`quantileState` sketches in an `AggregatingMergeTree`.
The [aggregation-rollups](../../patterns/aggregation-rollups/) group now
demonstrates the `-State`/`-Merge` mechanics with `argMin`/`argMax` states;
persisted `quantileState` sketches remain outstanding.

Background. This variant pre-aggregates the windowed p90 calculation instead of
keeping raw samples and computing the quantile at read time. Store
`quantileState` values in an `AggregatingMergeTree` and read them with
`quantileMerge`. The table retains per-window sketches, allowing the raw samples
to be dropped.

Demonstrates. `quantileState`/`quantileMerge` for incremental windowed quantiles,
and the storage/retention trade-off versus the raw-MergeTree approach.

Infra. `single` + `kafka`.

## Ingestion correctness

### insert-idempotency

Status. **Outstanding.** Related:
[kafka-push-exactly-once](../../patterns/kafka-to-clickhouse/kafka-push-exactly-once/)
validates Kafka Connect's KeeperMap-backed reprocessing behavior. The native
insert-block deduplication, `insert_deduplication_token`, and
`ReplacingMergeTree(version)` mechanisms proposed here remain unexercised.

Background. At-least-once producers and retried batches can send the same data
more than once. ClickHouse provides several deduplication mechanisms. Replicated tables
deduplicate identical insert blocks by content hash; `insert_deduplication_token`
sets the dedup key explicitly so retries are idempotent even across
sessions or when block content differs slightly; and `ReplacingMergeTree` with a
version column deduplicates logically by sort key.

Demonstrates. Insert the same batch twice and assert the row count does not
change (block dedup on a Replicated table), then show `insert_deduplication_token`
making a retry idempotent, and `ReplacingMergeTree(version)` collapsing duplicates
by key. Measurements can report parts created and deduplication events.

Infra. `cluster` (block dedup needs Replicated) or `single` (ReplacingMergeTree).

References.
[Insert deduplication](https://clickhouse.com/docs/guides/developer/deduplication),
`insert_deduplication_token` in
[settings](https://clickhouse.com/docs/operations/settings/settings).

### late-and-out-of-order-events

Status. **Partially implemented.** Angle A (resolve latest entity state in
ClickHouse) remains outstanding. Angle C (unordered object arrival) is
implemented by
[s3queue-unordered](../../patterns/s3-to-clickhouse/s3queue-unordered/), with
[s3queue-ordered](../../patterns/s3-to-clickhouse/s3queue-ordered/) as the
filename-watermark contrast. Angle B (event-time lateness with a stateful
processor) remains outstanding, as does the multi-table causal-ordering
question.

Background. An unreliable or parallel source can deliver old row versions,
late event-time records, duplicate retries, or files in an unexpected order.
Those are not equivalent failures:

- A versioned entity can often be resolved in ClickHouse by keeping the row
  with the greatest source version and retaining a versioned deletion marker.
- An event that arrives after an event-time window needs an explicit lateness
  policy and possibly a correction/retraction, not merely a greater row version.
- An object arriving late in S3 needs discovery that does not assume lexical
  filename order; it says nothing about the semantic order of records inside it.
- Changes from several relational tables may have a transactional or causal
  relationship which cannot be reconstructed from arrival timestamps alone.

Angle A, resolve latest entity state in ClickHouse. Send versions in the order
`1, 3, 2`, followed by a deletion at version `4`, then replay version `3`.
Demonstrate `ReplacingMergeTree(version, deleted)` or an explicit `argMax`
query. This approach requires the source to provide a monotonic version with the
required scope but does not depend on a specific source technology.

Angle B, event-time processing. Send events before and after a window is
considered complete. Compare accepting late data and rebuilding the result,
with a stateful processor using watermarks and allowed lateness. Kafka can
retain and partition these events, but it does not itself decide the watermark
or repair a completed result.

Angle C, unordered object arrival. Write files and backfills in a deliberately
non-lexical order and show unordered `S3Queue` or object-storage ClickPipes
discovering each file. This is file ingestion correctness, not record
reordering, and should not be presented as solving Angle A or B.

Candidate validation. Every variant should print the arrival order, the
semantic version/event time, the final accepted rows, and the policy that made
that result correct. A row-count check alone would not distinguish the version,
event-time, and file-arrival policies.

Open questions.

- Do version order, event-time lateness, and unordered files belong in one
  comparison or in three smaller patterns?
- Which guarantees should come from the source (LSN, binlog position, entity
  version, transaction id), and which should be created by the pipeline?
- Is the target current state, an immutable history, or both?
- What is the allowed lateness, and how is a result corrected after that bound?

Infra. `single` for entity versions; `single` + `kafka` plus a stateful worker
for watermarks; `single` + `s3` for unordered objects.

References.
[ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree),
[S3Queue](https://clickhouse.com/docs/engines/table-engines/integrations/s3queue),
[Flink event time and watermarks](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/time/).

## Buffering and decoupling

### buffered-ingestion-during-clickhouse-outages

Status. **Outstanding; comparative design, not a selected technology.**
Angle C's native mechanism is now runnable:
[s3queue-ordered](../../patterns/s3-to-clickhouse/s3queue-ordered/) and
[s3queue-unordered](../../patterns/s3-to-clickhouse/s3queue-unordered/)
implement S3Queue file ingestion; the outage/replay comparison across the three
architectures remains outstanding.

Background. A buffer separates producer availability from ClickHouse
availability and provides somewhere for backpressure to accumulate. It does
not, by itself, resolve semantic duplicates, late entity versions, event-time
windows, or multi-table joins. Compare three architectures with the same outage
and replay scenario.

Angle A, direct delivery. The producer batches and retries ClickHouse inserts.
This has the fewest components and may be sufficient when the producer can
spool locally and ClickHouse outages are bounded. The pattern needs to make the
loss/backpressure boundary explicit rather than using direct delivery as an
unexamined baseline.

Angle B, Kafka as a durable log.

```text
producer -> Kafka partitions -> consumer/connector -> ClickHouse
```

Kafka provides durable replay, ordered records within a partition, and consumer
coordination. It supports several independent consumers, keyed ordering, and
stateful streaming stages. It also adds a distributed system and does not create
a global record order across partitions.

Angle C, object storage as a batch buffer.

```text
producer -> batches + manifest in S3 -> consumer -> ClickHouse
```

Two related but distinct mechanisms should not be conflated:

- `S3Queue` discovers and tracks files, then an incremental materialized view
  can transform their rows into a durable table.
- OpenData Buffer defines a producer/consumer protocol over objects and a
  manifest. Its published ClickHouse integration uses at-least-once delivery,
  stable batch identities, and sink-side deduplication.

The OpenData design intentionally is not a general ordered log. Its current
description guarantees ordering within one ingestor and recommends a limited,
fixed number of participants. This may suit append-only logs, metrics, and a
small number of sinks. Causally related multi-table CDC requires separate
evaluation.

Shared experiment. Start a producer, make ClickHouse unavailable, continue
producing, then recover ClickHouse and drain the backlog. Force at least one
consumer retry. Report:

- accepted, buffered, delivered, duplicated, and missing records;
- time until the producer first experiences backpressure;
- recovery/drain time and end-to-end latency;
- the unit of replay and deduplication (record, Kafka offset, file, or batch);
- behavior with one versus multiple consumers;
- what happens when buffer retention or local spool capacity is exhausted.

Open questions.

- Is the workload append-only telemetry, versioned entities, or relational CDC?
- Is ordering needed per entity, per producer, per transaction, or not at all?
- Does the workload require multiple independent consumers and long retention,
  or would those Kafka capabilities remain unused?
- Should an object-buffer pattern use native `S3Queue`, OpenData Buffer, or show
  both while making their different responsibilities explicit?
- Which cost and throughput claims can the local harness measure fairly? The
  published OpenData benchmarks are useful inputs, not results we should repeat
  as universal conclusions.

Infra. `single`; add `kafka` for Angle B or `s3` plus a producer/consumer runtime
for Angle C. OpenData Buffer may need new images or small one-shot components.

References.
[OpenData Buffer design and tradeoffs](https://www.opendata.dev/blog/buffer-ha-pipelines-without-kafka),
[OpenData ClickHouse ingestion benchmark](https://www.opendata.dev/blog/ingesting-1gbps-logs-to-clickhouse),
[S3Queue](https://clickhouse.com/docs/engines/table-engines/integrations/s3queue),
[Kafka documentation](https://kafka.apache.org/documentation/).

## Modeling and enrichment

### cdc-denormalized-current-state

Status. **Outstanding; umbrella proposal under discussion.** The first decision
is whether this should be one comparative pattern or several patterns sharing a
fixture. No execution mechanism is selected yet.
Related:
[refreshable-materialized-views](../../patterns/aggregation-rollups/refreshable-materialized-views/)
demonstrates Angle C's mechanics (scheduled recompute with `FINAL` and a join
inside the refresh query) on a mark-to-market fixture, though not from CDC
landing tables.

Background. A relational source may have `customers`, `orders`, and
`order_items`, while the ClickHouse consumer wants one query-facing
`order_facts` table. CDC can keep three source-faithful landing tables current,
but it does not answer when to join them, what historical meaning copied
dimension values have, or how a derived result changes after an update or
delete.

Shared scenario. Replicate the three Postgres tables, construct the same
query-facing result with each candidate, then apply changes which expose their
different semantics:

- update an order status and amount;
- update a customer's country or tier;
- insert an order item after the order was first modeled;
- delete an item or an entire order;
- optionally deliver an older version after a newer one.

Before implementation, define the output grain (one row per order or item) and
choose deliberately between:

- **As-was:** a fact retains the dimension values valid when the transaction
  occurred.
- **As-is:** existing facts reflect the current dimension values after a
  customer or product changes.

Angle A, retain normalized tables and join at query time. This avoids maintaining
a duplicate wide table and returns the latest dimension values. It adds join
work to reads and may not meet a high-concurrency latency target. Dictionaries
can support stable one-to-one or many-to-one lookups but do not replace a
general three-table join.

Angle B, incremental materialized view. This can cast, filter, derive, or enrich
rows as inserts arrive. A joined incremental MV triggers only from its source
table; updates arriving in another landing table do not automatically re-emit
affected facts. It can implement stable dimensions or deliberate as-was
semantics, but it does not maintain arbitrary mutable joins.

Angle C, refreshable materialized view. Periodically recompute the join from
the resolved current state of all three CDC landing tables and atomically
replace the result. ClickHouse schedules the refresh, and the refresh interval
defines how stale the result may be. Full recomputation cost and refresh
frequency may become limiting factors. Dependencies can order refreshes.

Angle D, dbt. Express landing, current-state, conformed, and serving models as a
version-controlled DAG with tests. A full refresh recomputes the entire model.
Incremental dbt models reduce work but still need an invalidation strategy when
a customer update affects many existing facts. dbt organizes and executes the
SQL; it does not infer CDC retractions or affected join rows automatically.

Angle E, stateful stream processing. Publish source changes to a durable log,
maintain joined state in Flink/Kafka Streams, and emit an upsert/retraction
stream to ClickHouse. This can update the result continuously, but it introduces
checkpointing, state recovery, watermarks, schema evolution, and cross-stream
ordering questions.

Candidate validation. Each angle should produce the same initial result. After
each mutation, show whether it converges, how long it takes, which rows are
recomputed, and whether the result implements as-was or as-is semantics. Record
read cost, write amplification, refresh work, and operational components where
the harness can measure them. Equivalence at one final snapshot is necessary
but insufficient.

Open questions.

- Does the workload need a physical wide table, or can a query-time join meet
  its latency target?
- Is the freshness objective milliseconds, seconds, or minutes?
- How large are the source and derived tables, and is full recomputation
  acceptable?
- Are dimensions stable, slowly changing, or frequently corrected?
- Must historical facts change when a dimension changes?
- Should refreshable MV and dbt be compared in one runnable pattern because
  they execute the same SQL shape, or kept separate to show their operational
  differences?
- Is a stateful Kafka/Flink variant still a ClickHouse pattern, or an ecosystem
  pattern whose ClickHouse portion is only the sink and serving model?

Infra. Start with `postgres` + one existing CDC implementation + `single`.
The dbt angle needs a one-shot dbt runner. Stateful streaming needs `kafka`, a
Debezium source path, and a Flink/Kafka Streams worker, so it is substantially
heavier and should only be added if the latency requirement justifies it.

References.
[When to denormalize and when to join](https://clickhouse.com/resources/engineering/when-to-denormalize-when-to-join),
[Incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view),
[Refreshable materialized views](https://clickhouse.com/docs/materialized-view/refreshable-materialized-view),
[dbt and ClickHouse](https://clickhouse.com/docs/integrations/dbt),
[Flink event time and watermarks](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/time/).

### dictionary-enrichment

Status. **Outstanding.**

Background. ClickHouse dictionaries support point lookups without running a
`JOIN` at query time. A dictionary loads a source (a table, file, HTTP endpoint,
or another ClickHouse) into memory, is queried with `dictGet`, and refreshes
according to its `LIFETIME`.

Demonstrates. Define a dictionary over a small dimension table, enrich event rows
with `dictGet` (in a query or a materialized column), and show refresh via
`LIFETIME`. Contrast latency and ergonomics with the equivalent JOIN.

Infra. `single`.

References.
[Dictionaries](https://clickhouse.com/docs/dictionary),
[dictGet](https://clickhouse.com/docs/sql-reference/functions/ext-dict-functions).

## Catalog review findings (2026-08)

Outcome of a review of the reorganized catalog (the `aggregation-rollups`,
`database-to-clickhouse`, `kafka-to-clickhouse`, `clickhouse-to-kafka`, and
`s3-to-clickhouse` groups). Two suggestions from that review turned out to be
already covered: time-series downsampling rollups via incremental MVs writing
aggregation states to AggregatingMergeTree, including the cascaded variant
where the MV write boundary (the insert block) is smaller than the logical
bucket (the `aggregation-rollups` group), and incremental file ingestion (the
`s3-to-clickhouse` group). The entries below remain outstanding.

### kafka-poison-pill-dead-letter

Status. **Outstanding.**

Background. A malformed or schema-drifting message in a Kafka topic can stall a
Kafka-engine consumer: by default a parse error fails the whole block, and the
consumer cannot advance past the poison message. The Kafka engine supports
`kafka_handle_error_mode = 'stream'`, which exposes failed messages through the
`_error` and `_raw_message` virtual columns instead of failing the batch.

Demonstrates. A topic containing both valid and poison messages. One MV parses
valid messages into the serving table; the error stream is captured into a
dead-letter table holding `_raw_message`, `_error`, topic, partition, and
offset. The test asserts that all valid rows landed, the poison messages were
captured with their error text, and consumption advanced past them.

Infra. `single` + `kafka`.

References.
[Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)
(`kafka_handle_error_mode`, virtual columns).

### async-insert-batching

Status. **Outstanding.**

Background. Many small inserts create many small parts and eventually the "Too
many parts" error. The usual answers are client-side batching, server-side
asynchronous inserts (`async_insert = 1`, with `wait_for_async_insert` to make
the flush visible), and the Buffer engine as an in-server buffer.

Demonstrates. The same logical stream of small writes through three paths:
naive per-row inserts, client-batched inserts, and async inserts. Assert
identical final rows, and compare the part counts each path leaves in
`system.parts`. Record the flush-boundary and deduplication caveats of async
inserts in `tradeoffs`.

Infra. `single`.

Measurement. Part counts from `system.parts`; insert-path metrics per
[measuring-metrics.md](measuring-metrics.md).

References.
[Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts),
[Buffer engine](https://clickhouse.com/docs/engines/table-engines/special/buffer).

### json-landing-parse

Status. **Outstanding.**

Background. A common first processing level lands raw JSON payloads untouched
and extracts typed columns with a materialized view, keeping the raw copy for
replay and schema drift. ClickHouse also offers the `JSON` type with dynamic
paths and materialized subcolumns as an alternative.

Demonstrates. A raw landing table (`String` or `JSON` column), an MV extracting
typed columns into a serving MergeTree, and a payload that gains a new field
mid-stream. Contrast explicit `JSONExtract*` extraction with `JSON` dynamic
paths. Pairs naturally with [kafka-poison-pill-dead-letter](#kafka-poison-pill-dead-letter)
for parse failures.

Infra. `single` (add `kafka` only if the source matters).

References.
[JSON data type](https://clickhouse.com/docs/sql-reference/data-types/newjson).

### projections-vs-mv

Status. **Outstanding.**

Background. Projections accelerate aggregate queries without maintaining a
separate rollup table: ClickHouse stores the projection and keeps it consistent
with the base table. This is the in-table alternative to the fan-out MV
approach in
[materialized-view-rollups](../../patterns/aggregation-rollups/materialized-view-rollups/).

Demonstrates. The same trades-to-candles fixture as the `aggregation-rollups`
group: an aggregate projection answering the one-minute candle query,
contrasted with the MV-owned `candles_1m` table. Assert equal results, and
record how projection DDL, backfill (`MATERIALIZE PROJECTION`), and ownership
semantics differ from a separate table.

Infra. `single`.

References.
[Projections](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree#projections).

### ttl-rollup-downsampling

Status. **Outstanding.**

Background. The third TTL action family, after `DELETE` and moves: a
`TTL ... GROUP BY` rollup aggregates expired detail rows into summary rows
inside the same table during the TTL merge. This is retention-driven
downsampling, distinct from the MV-driven rollups in `aggregation-rollups` and
from the retention-cost comparison in
[ttl-delete-mixed-retention](#ttl-delete-mixed-retention).

Demonstrates. A table with a `GROUP BY` TTL that rolls raw rows older than a
boundary into per-minute aggregates while recent raw rows stay intact. Assert
raw rows before the boundary and rollup rows after it.

Infra. `single`.

Measurement. Forced TTL (`ALTER TABLE ... MATERIALIZE TTL`) with event times in
the past; `system.part_log` per [measuring-metrics.md](measuring-metrics.md).

References.
[Manage data with TTL](https://clickhouse.com/docs/guides/developer/ttl).
