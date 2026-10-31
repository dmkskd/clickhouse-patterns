# Walshadow pattern review and implementation handoff

Reviewed: 2026-10-28. This is a review and proposed revision, not an implemented
change. The user requested a correctness and readability review, then asked for
this document to share with another agent. Preserve the style of the other
patterns rather than turning this page into a standalone article.

## Scope and conclusion

Target: `patterns/database-to-clickhouse/cdc-postgres-walshadow/`.

The running demo passed `just validate`. ClickHouse's current-state result
matched Postgres after the demonstrated INSERT, UPDATE, DELETE and
`ADD COLUMN status text DEFAULT 'new'`. The engine, key and added default also
matched the intended design.

The page explains the central architecture reasonably well, but mixes general
walshadow capabilities with the actual demo configuration. Correct those
differences, move the explanation of the shadow earlier, and shorten the text.
No new page template or Explorer-wide redesign is needed.

Validation establishes the demonstrated end state. It does not establish
performance, restart recovery, failover, large-value handling or all supported
schema changes.

## Repository style comparison

Read these as style references, not as independently audited technical claims:

| Pattern | Useful convention |
| --- | --- |
| [Postgres via PeerDB](../../patterns/database-to-clickhouse/cdc-postgres-peerdb/pattern.yaml) | Starts with the mechanism, identifies what the demo replicates, explains staging and service roles, and puts decision criteria in `tradeoffs`. |
| [Postgres via Debezium and Kafka](../../patterns/database-to-clickhouse/cdc-postgres-kafka/pattern.yaml) | Leads with the reason to choose the architecture; explains the actual transforms; graph has a separate current-state query lane. |
| [MySQL via Altinity sink](../../patterns/database-to-clickhouse/cdc-mysql-clickhouse/pattern.yaml) | Uses a short snapshot/streaming list, distinguishes target ownership, and explains versions and tombstones in ordinary prose. |
| [Scheduled Postgres pull](../../patterns/database-to-clickhouse/postgres-refreshable-pull/pattern.yaml) | Connects the mechanism to read semantics and suitability; benefits and limitations explain concrete consequences. |
| [Postgres table engine](../../patterns/database-to-clickhouse/postgres-table-engine/pattern.yaml) | Opens with one direct sentence, then explains the available mechanisms and their query behavior. |
| [Materialized-view rollups](../../patterns/aggregation-rollups/materialized-view-rollups/pattern.yaml) | Keeps the description short and explains what happens on insert and on read. |

Common structure:

1. `metadata.description`: mechanism, actual example, important read semantics
   and architectural distinctions, usually a few paragraphs with an occasional
   short list.
2. `metadata.graph`: named data paths and concrete resources; shared Explorer
   controls already expose manifest, DDL, loader and validation.
3. `metadata.tradeoffs`: selection criteria with practical consequences.
4. `metadata.references`: upstream evidence and further reading.
5. `spec.steps`: executable setup and verification, separate from catalog prose.

The descriptions sampled above do not use the walshadow page's succession of
delivery, operational and internals headings. Follow their prose-led approach.
The earlier review's suggestion of six visible article sections should therefore
be treated as a logical ordering of content, not a proposed new page format.

The authoring model is documented in
[pattern-model.md](../../.agents/skills/clickhouse-pattern-author/references/pattern-model.md).
In particular, graph notes should be compact factual annotations, snapshot and
change paths should be distinct, and a query lane is appropriate when read
semantics are part of the design decision.

## Evidence from the live review

The session reported `phase: validated`, `source_changed: false`, and used the
library pattern directory above. A separate `just validate` passed all three
convergence checks and the expected-output comparison.

Both Postgres and `walshadow.public_orders FINAL` returned:

| id | customer | amount | status |
| --- | --- | --- | --- |
| 1 | alice | 100 | new |
| 2 | bob | 250 | new |
| 4 | dave | 400 | shipped |

Observed destination definition:

```sql
CREATE TABLE walshadow.public_orders (
    id Int32,
    customer Nullable(String),
    amount Nullable(Int32),
    _lsn UInt64,
    _xid UInt32,
    _commit_ts DateTime64(6, 'UTC'),
    _is_deleted Bool,
    status Nullable(String) DEFAULT 'new'
)
ENGINE = ReplacingMergeTree(_lsn, _is_deleted)
ORDER BY (id);
```

Other observations:

- Postgres reported `wal_keep_size = 0` and no replication slots.
- Generated `/etc/walshadow/ch-config.toml` set
  `[table.public.orders] initial_load = "copy"`, `replicate = true`, and omitted
  an explicit `[stream] replicate_all = false`.
- `walshadow.public_orders_existing` also existed in ClickHouse.
- Bootstrap logs reported a backup page walk and six tuples emitted, then a
  separate `public.orders` backfill with `rows=3` and `copied=true`.
- A bootstrap warning said a requested WAL segment had already been removed;
  the process recovered the backup window from WAL supplied by the backup.

These observations describe that run, not a guarantee about a future session.
Rediscover the session before further live work.

## Corrections and missing context

### 1. Initial load: describe both bootstrap and COPY

The current text and snapshot graph present backup heap-page loading as the
whole initial-load path. In this run, the shadow bootstrap used a physical
backup and `orders` also completed its configured COPY backfill.

Do not replace the text with the equally incomplete claim that startup uses
only COPY. Explain the distinction and show the configured COPY path in the
graph. Keep the distinction brief enough for the neighboring pattern style.

If the implementation is changed to use a different load mode, verify that mode
against the pinned upstream revision and rerun the demo before documenting it.

### 2. Scope: `orders_existing` is shared seed data

`compose/cdc/postgres-init.sql` creates and seeds both `orders` and
`orders_existing`. They are repository fixtures, not built-in Postgres tables.
Their presence on the source is expected and is not a defect.

The review finding concerns replication scope: the generated walshadow config
does not restrict replication to the one table named in the diagram. The pinned
configuration documentation says the omitted stream setting leaves broad
replication enabled, consistent with the extra destination observed live.

Recommended minimal correction: say the demo focuses on `orders`, while the
generated defaults also replicate the shared `orders_existing` fixture. Do not
delete the fixture or change shared Postgres initialization to make the diagram
appear correct. Restricting replication is an alternative implementation choice,
not a prerequisite for an honest page.

### 3. Retention: name the actual demo limitation

The sentence that the pattern “relies on `wal_keep_size`” is misleading because
no additional retention is configured. It was zero in the reviewed run, with no
physical slot or archive. That does not mean Postgres retains no WAL at all;
it means there is no extra retention budget from that setting.

Suggested wording: “This disposable demo configures no physical slot, WAL
archive or additional WAL retention. A deployment must retain enough WAL to
cover outages and backlog.” Explain that unrecoverable gaps stop replication.

If adding a slot or another retention mechanism, treat it as a runtime change
with lifecycle and storage implications, not a prose correction. Do not silently
make a shared Compose change during a page edit.

### 4. Schema evolution: qualify capability claims

The current “applies each ADD COLUMN, RENAME COLUMN and DROP COLUMN” wording is
too broad. The pinned upstream documents qualify behavior for explicit mappings
and ClickHouse restrictions, especially sorting-key changes that can stop
replication. This demo exercises only `ADD COLUMN ... DEFAULT`.

Replace the universal logical-decoding comparison about renames becoming
drop-plus-add. Standard Postgres logical replication does not transmit DDL
commands; connector-specific schema handling varies. Describe walshadow's
catalog-tracking mechanism and supported schema evolution without asserting a
universal behavior for competing clients.

### 5. Performance: attribute rather than promise

“Latency in the low hundreds of milliseconds” is an upstream benchmark claim,
not a result measured by this demo. Prefer omitting the number from the lead.
If retained elsewhere, attribute approximately 200 ms to the launch benchmark
and link its workload and environment.

### 6. Explain the shadow earlier and define the terms it needs

The strongest explanation currently appears after delivery and operational
details. Bring this idea near the beginning:

> The shadow replays catalog changes so walshadow can interpret row records
> using the schema that existed when those records were written.

Explain that original WAL records go to the row decoder while filtered WAL goes
to the shadow. The shadow is not an ordinary full user-data replica. Define LSN
once as a WAL position used for progress and row versioning. Explain why physical
streaming still requires `wal_level = logical`; stream transport and the amount
of information recorded in WAL are different choices.

Avoid describing “a physical WAL record” as necessarily a heap-row change;
physical WAL also contains catalog, transaction and other record types.

### 7. Read semantics and usable identity

Move the explanation of row versions and delete markers before operational
details. Include the actual query, or point directly to `verify.sql`:

```sql
SELECT id, customer, amount, status
FROM walshadow.public_orders FINAL
ORDER BY id;
```

For this generated `ReplacingMergeTree(_lsn, _is_deleted)` table in its default
mode, `FINAL` returns current live rows. Do not copy a mandatory tombstone filter
from sibling connectors whose destination engines or soft-delete settings differ.
Ordinary reads can expose multiple versions before merges reconcile them.

Mention that replicated tables need a usable replica identity; this demo uses
the primary key `id`. Do not imply that arbitrary mutable sorting keys are safe.

### 8. Recovery state and large values

The page already mentions state survival, but should identify the deployment
boundary: this Compose service has no explicit persistent mount for walshadow's
state. Container restart and container replacement have different consequences;
the demo is disposable and should not imply durable production recovery.

Keep config, shadow data, filtered WAL and spill/manifests together for recovery,
as upstream documents. Do not reduce the requirement to `manifest.toml` alone.

Qualify “complete new tuple”: unchanged externally stored values can require
TOAST reconstruction. A short caveat and upstream link are sufficient; avoid
expanding the pattern into a large-value implementation tutorial.

## Proposed revision in the existing style

Use roughly six compact paragraphs, with at most a short two-phase list:

1. What walshadow does and where decoding runs.
2. What this demo changes and verifies; acknowledge the shared extra fixture.
3. Why the shadow exists and how original/filtered WAL split.
4. Bootstrap versus configured COPY backfill, followed by ongoing changes.
5. Versions, tombstones and `FINAL` current-state reads.
6. The few constraints necessary to interpret this example: logical WAL level,
   matching major version, usable identity and disposable retention/state.

Possible opening, to be integrated with the rest rather than pasted as a new
standalone section:

> walshadow reads Postgres physical WAL, decodes committed row changes outside
> the source database, and writes them directly to ClickHouse. A managed shadow
> Postgres maintains the schema information needed to interpret those records.

Keep schema evolution and source decoding work as concise architectural
distinctions. Put detailed recovery/failover procedures and protocol commands in
upstream references, or a small companion README only if genuinely needed.
Preserve the standard page's trade-offs and references rather than repeating
their content in multiple description sections.

Benefits should explain consequences: decoding outside the source; direct
Native inserts without Kafka or an object-store staging service; supported
schema changes ordered relative to rows. Limitations should explain physical
access/version coupling, retention and state requirements, eventual consistency,
and preview maturity. Avoid unsupported quantitative performance comparisons.

Graph changes should preserve `snapshot`, `changes` and `catalog` lanes, represent
the actual COPY path alongside bootstrap, and add a small `query` lane for
`SELECT ... FINAL`. Keep component annotations short. If the diagram focuses
on one table, say so instead of pretending the wider scope does not exist.

## Visual observations, separate from pattern changes

The rendered page's paragraphs span very long lines and repeated bold product
names compete with substantive emphasis. Reduce repetition in this pattern's
text first. A global line-width change would affect other pages and belongs in
a separate Explorer change.

The inspected diagram was at 50% zoom: its labels were tiny despite the large
panel. This is an observed viewer state, not proof of a faulty default. Check
reset/fit and saved zoom preferences before proposing a renderer fix. Do not
bundle an Explorer-wide redesign with this pattern review.

## Sources to use for implementation

The Compose image is pinned to upstream commit
`97f9305316eb5ff89cb3e0071eff095722db4143`, built for Postgres 16. Verify behavior
against that revision; mutable `main` links may describe later behavior.

- [Pinned architecture](https://github.com/ClickHouse/walshadow/blob/97f9305316eb5ff89cb3e0071eff095722db4143/architecture/README.md)
- [Pinned configuration](https://github.com/ClickHouse/walshadow/blob/97f9305316eb5ff89cb3e0071eff095722db4143/docs/configuration.md)
- [Pinned limitations](https://github.com/ClickHouse/walshadow/blob/97f9305316eb5ff89cb3e0071eff095722db4143/docs/limitations.md)
- [Pinned destination tables](https://github.com/ClickHouse/walshadow/blob/97f9305316eb5ff89cb3e0071eff095722db4143/docs/destination-tables.md)
- [Pinned schema changes](https://github.com/ClickHouse/walshadow/blob/97f9305316eb5ff89cb3e0071eff095722db4143/docs/schema-changes.md)
- [Pinned operations](https://github.com/ClickHouse/walshadow/blob/97f9305316eb5ff89cb3e0071eff095722db4143/docs/operations.md)
- [Pinned failover](https://github.com/ClickHouse/walshadow/blob/97f9305316eb5ff89cb3e0071eff095722db4143/docs/failover.md)
- [Postgres 16 logical replication restrictions](https://www.postgresql.org/docs/16/logical-replication-restrictions.html)
- [Launch benchmark and its conditions](https://clickhouse.com/blog/introducing-walshadow)

## Implementation boundaries and acceptance

This document records proposals; it does not authorize destroying a live session.
Follow the repository authoring and lab skills when implementing. Preserve
unrelated working-tree changes. The review saw existing modifications in
Explorer files, manifest/rendering code and tests, plus unrelated new patterns
and proposals; do not revert or overwrite them.

Before live work, run `just status --json` and read the exact reported pattern
directory. Do not start another pattern over an active session, reload as part
of inspection, or stop a browser/foreground session automatically. Use read-only
database inspection for the review.

For a later implementation:

- Match the prose-led neighboring pages and retain the manifest structure.
- Resolve the corrections above without suggesting the shared seed is a bug.
- Keep tested behavior distinct from upstream capabilities and benchmarks.
- Keep text, graph, configuration and verification consistent.
- Do not silently change runtime scope, retention or shared Compose defaults.
- Run `just show cdc-postgres-walshadow` and
  `just diagram cdc-postgres-walshadow`; inspect the rendered result.
- Run the authoring skill's required checks:
  `uv run pytest -q tests/test_architecture.py tests/test_clones.py tests/test_cli.py`.
- If runtime changes are made, rebuild only through an intentional authorized
  iteration and run `just validate`; without an active session use
  `just test cdc-postgres-walshadow`. Report which behavior was actually tested.

During the original review, a startup attempt initially failed because
`tracehouse-dev` occupied host ports 8123 and 9000. The user resolved it and the
walshadow demo subsequently validated. This is historical context, not a current
failure or permission to stop TraceHouse.
