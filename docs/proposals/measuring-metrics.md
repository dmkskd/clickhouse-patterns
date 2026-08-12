# Capturing operational metrics

## Motivation

The harness compares query results (`verify.sql` and `expected.txt`) and polls
scalar values with `wait_for`. Some patterns must also compare operational work,
including bytes rewritten, parts created, and merges performed.

The three TTL retention options in
[outstanding-patterns.md](outstanding-patterns.md#ttl-delete-mixed-retention) end with
the same rows present. They differ in bytes rewritten by TTL merges, the number
of merges and mutations, and whether parts are dropped or rewritten. Query
results alone cannot show those differences.

The same capability could measure read and storage amplification in sharded
Kafka ingestion, bytes moved by backups, and parts or merge pressure created by
the Kafka engine.

## Proposed capability: a `measure` section

Add an optional `measure` list to `pattern.yaml`. Each entry runs a query against
system tables at the end of the run, and the harness records its result. An
optional bound turns the measurement into an assertion.

```yaml
measure:
  - name: ttl_rows_rewritten
    query: >
      SELECT sum(rows) FROM system.part_log
      WHERE table = 'user_events_raw' AND merge_reason = 'TTLDeleteMerge'
  - name: parts_dropped
    query: >
      SELECT count() FROM system.part_log
      WHERE table = 'user_events_raw' AND event_type = 'RemovePart'
    equals: 3            # optional bound; violate it and the pattern fails
```

Runner changes:

- After `load` and `ready_when`, run `SYSTEM FLUSH LOGS` on the driver (system log
  tables are buffered).
- Run each `measure` query, capture the scalar into `Result.measurements`.
- The CLI prints them under the checks. If a bound (`equals` / `max` / `min`) is
  set and violated, the pattern fails.

Without a bound, the harness prints the measurement without affecting the test
result. With a bound, a value outside the allowed range fails the pattern.

## System tables used for measurement

- `system.part_log`: `MergeParts` events with `merge_reason`
  (`TTLDeleteMerge`, `TTLRecompressMerge`, `RegularMerge`), `rows`, `read_bytes`,
  `size_in_bytes`. These fields record the work performed by TTL merges.
  `RemovePart` events count dropped parts.
- `system.merges`: in-flight merges (for watching, not final measurement).
- `system.mutations`: `ALTER DELETE`/`UPDATE` progress and counts.
- `system.parts`: current parts, rows, bytes; count parts before/after.
- `system.metrics` and `system.events`: counters.

## Determinism

- TTL merges are asynchronous and time-based (`merge_with_ttl_timeout`, default
  4h). To measure deterministically, force them with `OPTIMIZE TABLE ... FINAL`
  or `ALTER TABLE ... MATERIALIZE TTL`, and set event times in the past so rows
  are already expired.
- `SYSTEM FLUSH LOGS` before reading `system.part_log`.
- Metrics are per-node; on a cluster, measure on the specific node.

## Comparing TTL strategies

The row-level `DELETE WHERE` strategy rewrites surviving rows, while the
partitioned-retention strategy uses `DROP PARTITION` without rewriting them.
The harness could express this comparison in two ways:

1. Absolute bounds per pattern. The partition-drop pattern sets
   `ttl_rows_rewritten` to `max: 0`; the row-level TTL pattern sets an expected
   lower bound.
2. A cross-pattern comparison that runs both patterns and reports the difference
   between their `measurements`.

Implement per-pattern measurements and bounds first. Cross-pattern comparison
can be added separately.
