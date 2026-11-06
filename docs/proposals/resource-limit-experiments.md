# Observing resource limits through experiments

Status: **partially implemented**. The
[read/write traffic experiment](../../patterns/resource-limits/protect-inserts-from-selects/README.md)
implements parameterized arrivals, reader admission limits, query-log evidence
and a request Gantt column. Baseline and protected traffic runs have been
exercised on ClickHouse 26.9. The queue-wait scenarios below remain proposed.

The same pattern now includes `protect-writes-memory`, using separate reader
and writer WORKLOADs and a MEMORY RESERVATION resource. It reuses the traffic
generator and request timeline, with mixed reservation sizes, a reader memory
budget and a bounded admission wait. Scheduler allocations, pending requests
and rejection counters are saved alongside client outcomes. The per-user
query-count limit is disabled for this case, then restored. Memory reservations
are declared requirements; actual query memory remains a separate measurement.

Builds on the [existing experiment framework](experiments.md)
and the [resource limits review](../reviews/resource-limits-review.md).
The remaining workloads and measurements below describe planned extensions.

## Per-query reservation visibility

Inspection of the running ClickHouse 26.9.18.11 server found
`MemoryReservationAdmitMicroseconds` in per-query `ProfileEvents`. It records
the duration of the initial memory admission wait. It does not identify the
absolute acquisition time or release time. `MemoryReservationIncreases` counts
approved increases without recording their timestamps or sizes.

The current experiment retains these counters in each request's query-log
evidence. Scheduler observations record aggregate allocated bytes and pending
request counts. Client intervals include admission, execution and network time.
Combining these measurements does not establish each query's allocation interval.
A query rejected before admission must not be drawn as occupying reserved memory.

Two representations are possible:

- Requested-memory blocks can show each SELECT's declared reservation size and
  client interval, with sampled allocated memory overlaid. They must be labelled
  as requested capacity, without assigning an inferred admission timestamp.
- An allocation replay requires events containing the query ID, workload,
  scheduler timestamp, approved byte change and release. The inspected scheduler
  source contains allocation approval debug statements, but their logging is
  disabled by compile-time switches in `Common/Scheduler/Debug.h`. Enabling a
  server log level alone does not enable those statements. A custom build and
  validation against the aggregate scheduler samples would be required.

The visual design must preserve the distinction between declared demand,
observed allocations and rejected requests. Hovering the existing resource plot
reports both metrics and the timestamps of their latest observations.

## First experiment: concurrency admission

Make `server-concurrency-wait-vs-reject` runnable and give it an admission
experiment. Demonstrate three outcomes with the same small workload:

| Case | Settings | What the user should see |
|---|---|---|
| Reject | `max_concurrent_queries=2`, `queue_max_wait_ms=0` | Two blocker queries occupy the slots; excess queries fail before execution. |
| Wait, then run | Same server limit, wait budget longer than the blockers' remaining duration | Excess queries wait, then complete as slots become free. |
| Wait, then reject | Same server limit, wait budget shorter than the blockers' remaining duration | Excess queries wait and fail with `TOO_MANY_SIMULTANEOUS_QUERIES`. |

Use bounded queries lasting roughly two seconds for blockers, and a small number
of short probe queries. The script waits until both blockers are observed in
`system.processes` before dispatching probes; a thread barrier alone would not
prove server admission. The exact query and duration need validation on the
pinned server. A sleep-based query is suitable for occupying slots, but should
not be described as a CPU load.

Start with a single node on the repository's pinned ClickHouse 26.9 image.
Run the cases sequentially, changing only the admission setting being compared.
Disable other restrictive concurrency/profile settings in the isolated lab so
they cannot mask the intended check. Record the effective settings and server
version with every result.

Expected query rejection is an experiment observation, not a failed script.
The experiment fails only if setup, collection, cleanup, or its behavioral
assertions fail. Do not assert exact millisecond timings or a particular queue
order.

## What the output should show

Keep the existing results table and average-duration bar for comparing runs.
Add an expandable timeline with one lane per request, sharing the experiment's
time origin. This reveals concurrency and queueing that an average conceals:

```text
                         time since experiment start →
blocker 1                [ executing                 ] ✓
blocker 2                [ executing                 ] ✓
probe 1                       [ admission wait ][ run ] ✓
probe 2                       [ wait ] × TOO_MANY_SIMULTANEOUS_QUERIES
```

The illustration combines outcomes to explain the display; each initial test
case isolates one outcome. Show rejected requests as timed attempts ending in
an error marker, including attempts that never appear in `system.processes`.

For each run, print a terminal summary and save:

- Parameters and effective settings; server version; experiment/run ID.
- Submitted, completed, rejected and unexpectedly failed request counts.
- Error names/codes and the IDs of affected queries.
- Client elapsed p50/p95/max, measured queue/admission wait where available,
  maximum observed active queries and observation interval.
- Evidence coverage: which requests matched server logs, which measurements
  were unavailable, and whether admission timing was measured or estimated.

For each request, retain its ID, role (blocker/probe), submitted/completed
offsets, outcome, server error, matching terminal query-log row and useful
ProfileEvents. The user should be able to inspect the evidence behind a lane.

## Collect evidence at the client and in ClickHouse

1. Generate a run ID and unique query IDs. Give each concurrent worker its own
   client/session, including the observer. Avoid shared-session concurrency
   errors being mistaken for ClickHouse admission limits. Exclude collector
   queries from all workload counts.
2. Measure submission and completion with a client monotonic clock. These
   observations survive early rejection, disconnected clients, and absent log
   entries. Set finite client deadlines and disable automatic retries for the
   workload, so one logical attempt remains one attempt.
3. Sample `system.processes` about every 100 ms for the workload IDs to confirm
   blockers and observe executing queries. The observer must retain a way to
   query while the test slots are full. For this server-limit experiment,
   validate the special exemption for a simple SELECT from `system.processes`
   on the pinned release; do not assume a separate user bypasses the server
   limit. Collect heavier diagnostics after workload completion.
4. Enable query logging without probability sampling or minimum-duration/error
   filters that would remove the test attempts. Collect `QueryFinish`,
   `ExceptionBeforeStart` and `ExceptionWhileProcessing` from
   `system.query_log`, matched by query ID, retaining exactly one terminal
   outcome per request. After workers finish, flush logs through the runner's
   ordinary client and poll for expected entries within a deadline. Missing
   logs stay explicitly missing; client outcomes remain authoritative.
5. Inspect available ProfileEvents and their definitions on the pinned server.
   Use an admission-wait event only after checking its timing boundaries and
   aggregation semantics. Query-start timestamps must not be assumed to mean
   admission completion: validate their placement against the server code and
   a controlled run.
6. Where exact admission boundaries are unavailable, label process-list-derived
   intervals as sampled estimates with their resolution. Do not label
   `client elapsed - query_duration_ms` as exact queue time: it may include
   connection, parsing, transfer or overlapping server timing.

Use client offsets for the timeline axis. Keep raw server timestamps separately
instead of subtracting timestamps from different clocks. Server node identity
becomes part of the key when extending to a cluster.

For workload admission experiments added later, sample `system.scheduler` as
well: queued workload queries are absent from the process list. Scheduler
queue length measures resource requests, whose meaning depends on resource
type; it is not universally a count of waiting queries.

## Reuse and required changes

The existing implementation already provides:

- `spec.experiments` parameters, result labels and groups in
  `pattern_explorer/catalog/manifest.py`.
- Sequential comparison runs, config copies/reloads, script progress and
  `RESULT {json}` capture in `pattern_explorer/orchestration/experiments.py`.
- JSONL history in `.runtime/experiments/<slug>.jsonl` and result tables in
  `explorer/experiments.js`.
- Duration bars from `results.stages = [{label, ms, extra}]`.

Implement the remaining pieces in this order:

1. **Runnable pattern and bounded driver.** Add pattern-local configuration,
   setup/verification and an experiment script with blocker synchronization,
   independent clients, IDs, deadlines and cleanup. Keep deterministic pattern
   verification separate from the on-demand saturation workload.
2. **Server configuration parameters.** The config editor currently recognizes
   line-based `key=value`, `key: value` and JSON forms, not XML elements.
   Add structured XML-path editing and tests for the server fragment, or mount
   a ClickHouse YAML fragment and validate its merge/override behavior first.
   Prefer the supported YAML path if it works with the existing editor and
   stack. The ordinary `queue_max_wait_ms` parameter can be passed directly to
   each workload query without reloading. Keep the server limit fixed at two
   in the first version; making it adjustable can follow.
3. **Evidence collector.** Add a limits-family helper under
   `pattern_explorer/orchestration/pattern_specific/` for client outcomes,
   process samples and query-log correlation. Probe supported tables, columns
   and events before running; report missing capabilities. Do not extend the
   CDC-specific `cdc_latency.py` with unrelated admission logic.
4. **Results contract.** Preserve existing scalar results and `stages` for the
   initial summary. Define and validate optional `requests`, `samples` and
   `evidence` payloads for detailed results. The runner can save nested JSON
   today, but the UI currently renders only declared scalar columns and its
   duration bars. Add bounded sample/request counts to keep JSONL manageable.
5. **Timeline and CLI output.** Render request offsets, measured/estimated
   segments, terminal outcomes and evidence details. A true Gantt needs start
   offsets and parallel lanes; the existing sequential duration-bar renderer
   cannot express those. Print readable summary rows in the CLI and expose
   raw results for inspection.
6. **Guide navigation.** Link each exercised mechanism to its pattern and
   named experiment, showing supported version and observed evidence. The
   current `pattern` link can open a pattern, but does not select an experiment.

The first deliverable can use existing result columns and duration bars while
the detailed timeline follows. Only put non-overlapping wall-time phases in
an additive bar. CPU time and thread wait counters can accumulate across
threads and exceed elapsed time; show those as separate measurements.

## Follow-on experiments

| Family | Controlled comparison | Evidence and display |
|---|---|---|
| User concurrency | Per-user limit with free server slots | Query outcomes/logs and request lanes; demonstrate immediate rejection. |
| Workload query admission | Two query slots, queue bound and admission timeout | Scheduler samples, client outcomes and available admission events; separate workload and process-list waiting. |
| Memory versus spill | Same bounded aggregation, external aggregation enabled/disabled | Peak tracked memory, external-processing counters/bytes, temporary storage and outcome; memory series plus error marker. |
| IO or CPU rate | Same work with and without a throttle | Work completed, elapsed time, resource counters and throttle evidence; throughput/resource series rather than invented serial phases. |
| Execution bounds | Bounded query with row/time ceilings and overflow modes | Returned row count, terminal error and result completeness; explicitly identify partial results. |
| Parts backpressure | Small isolated table with deliberately low thresholds | Parts per partition, insert duration, delay evidence and errors; separate background merge activity. |
| Quota | Fixed small request batch with a low query-count quota | Quota usage before/after and outcomes; interval/key/initiator clearly identified. |

Run one mechanism at a time before testing interactions. Prefer bounded
per-query limits over saturating server memory. Experiments changing server
configurations use the existing session-reload lifecycle, which recreates lab
data; the Explorer should continue showing the applied configuration values.

`system.query_metric_log` can provide per-query resource histories when enabled
and configured for an appropriate sampling interval. Its default one-second
sampling is too coarse for many short probes. Process snapshots and metric
samples can miss short peaks, so distinguish maximum observed values from
authoritative peaks reported in terminal logs.

## Acceptance checks

- Rejection, successful waiting and queue timeout are demonstrated independently
  with observed server errors and effective settings.
- Every submitted attempt has a saved client outcome, even without a server log.
- Observers do not accidentally consume or bypass the tested workload slots.
- Repeated runs remain isolated by ID; expected rejections still produce saved
  results and a successful experiment verdict.
- Timing assertions allow sampling/scheduler variation; unknown timings render
  as unknown rather than zero.
- Worker queries are drained or cancelled on failure and user Stop. Terminating
  the script currently terminates its process; it does not establish that all
  remote queries were cancelled. Implement a cancellation path that can operate
  during saturation, with server-side maximum durations as a final bound.
- Tests cover log correlation, missing evidence, expected errors and result
  payloads. Validate all three cases live on the pinned image, then inspect the
  UI with real saved results before reporting the pattern as verified.

## References

- [Query log outcomes, IDs and ProfileEvents](https://clickhouse.com/docs/operations/system-tables/query_log)
- [Per-query sampled metrics](https://clickhouse.com/docs/operations/system-tables/query_metric_log)
- [Scheduler queues and resource state](https://clickhouse.com/docs/operations/system-tables/scheduler)
- [Admission ordering in ProcessList](https://github.com/ClickHouse/ClickHouse/blob/master/src/Interpreters/ProcessList.cpp)
- [Workload scheduling](https://clickhouse.com/docs/operations/workload-scheduling)

Use release-pinned source and runtime capability checks during implementation;
the upstream master references above are evidence to investigate, not a promise
that every event or column exists in 26.9.
