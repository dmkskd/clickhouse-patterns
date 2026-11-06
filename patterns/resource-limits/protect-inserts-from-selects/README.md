# Protecting inserts from SELECT load

SELECTs and INSERTs run on the same ClickHouse server under separate users.
Two experiments compare reader admission policies: a fixed per-user concurrency
limit and reservation-based admission under separate reader and writer workloads.
Both measure INSERT throughput and latency alongside SELECT rejections.

CPU, memory and storage remain shared. [ClickHouse Cloud warehouses](https://clickhouse.com/docs/cloud/reference/warehouses)
provide compute-compute separation with separate compute services sharing data.

## Traffic and policy

The `protect-writes` experiment runs CPU-bound SELECTs over `numbers()` alongside
INSERTs into `demo.events`. Each read hashes `read_rows` numbers and returns one
aggregate. Each INSERT writes `batch_rows` rows with a unique run ID.

| Parameter | Effect |
|---|---|
| `read_slots` | Reader concurrency limit; 0 disables the limit |
| `read_rate` | Requested SELECT requests per second |
| `read_shape` | `steady` spaces arrivals; `burst` submits each second's arrivals together |
| `read_rows` | CPU work per SELECT |
| `write_rate` | Requested INSERT requests per second, spaced evenly |
| `batch_rows` | Rows per INSERT |
| `duration` | Scheduled traffic duration in seconds |

The server has 32 process-list slots. Reader and writer requests use separate
connections. Reader rejection is controlled by the reader user's limit. User
settings are constrained with `CONST`. The experiment administrator changes
`read_slots` before dispatch and restores its previous value after draining requests.

The generator prepares capacity for all scheduled SELECT and INSERT requests
before traffic starts. Each request is attempted once. Generator dispatch
failures fail the experiment. Client timeouts and query failures have their
own counts. Older saved runs retain their original **not sent** outcomes.

## Comparing runs

Start the pattern, then compare identical traffic with the reader limit disabled
and enabled:

```sh
just start protect-inserts-from-selects
just experiment protect-writes read_slots=0 / read_slots=2
```

The Explorer's Experiments panel accepts multiple parameter rows and records
each run separately. Compare INSERT completions, failures, rows per second and
p95 client latency alongside SELECT rejections. Successful writes also depend
on server capacity, disk space and MergeTree backpressure.

The **Query admission** column opens the fixed-concurrency chart. The blue line
shows active requests sampled from `system.processes`, with the configured
reader concurrency limit drawn as a horizontal line. Green requests stack from
zero and amber rejected requests stack above them. The shared readout reports
sampled query counts and requests overlapping the replay cursor. Reader and
writer users have separate views.

The **Request timeline** column plots client request intervals on a common time axis,
with SELECT and INSERT lanes and outcome colors. Hovering a request shows its
query ID, elapsed time, error code and matching `system.query_log` entry.
These intervals include network and server execution. Admission and execution
phases are combined in the client measurement.

Clicking the preview opens a larger timeline with zoom controls and horizontal
scrolling. The Fit control restores the full comparison interval.

## Evidence

- Client query IDs identify every dispatched request and its outcome.
- `system.query_log` supplies final events, errors, memory usage and
  `ProfileEvents`. Results report the count of matched requests.
- `system.processes` is sampled every 20 ms. The peak active-reader count is
  a sampled maximum and can miss short requests.
- The experiment checks `demo.events` rows against acknowledged INSERT batches.
  A mismatch fails the experiment.
- Completed runs and request evidence are saved under
  `.runtime/experiments/protect-inserts-from-selects.jsonl`.

Stopping the experiment stops dispatch, cancels matching query IDs and drains
workers. Each query also has a five-second server execution limit and a finite
client timeout. A normal pattern stop removes its lab data; saved results remain.

## Workload memory admission

The `protect-writes-memory` experiment uses the same generator and table, with
a different admission policy. It creates a `MEMORY RESERVATION` resource and
separate reader and writer `WORKLOAD`s for each run. The existing per-user
query-count limit is disabled during this run and restored afterward.

This is reservation-based admission control. Clients declare a memory reservation
for each query with `reserve_memory`, and the server enforces the workload's
budget. Controlled reservation sizes make the admission decisions easier to
illustrate. Server-configured defaults and setting constraints can govern the
reservation values clients supply.

A separate experiment could demonstrate safeguards based on actual memory
consumption. The queries that fail would depend on timing, concurrency and
runtime allocations.

| Parameter | Effect |
|---|---|
| `read_memory_mib` | Reader workload's total memory-reservation budget; 0 disables the budget |
| `read_reserve_mib` | Memory reservation per SELECT, or the large reservation in mixed traffic |
| `reservation_mix` | Same size (`uniform`) uses `read_reserve_mib` for every SELECT. Alternate (`mixed`) alternates 8 MiB and `read_reserve_mib`. |
| `admission_wait_ms` | Maximum wait for workload admission |

For example, an 8 MiB reservation and a 32 MiB reservation consume different
amounts of a 64 MiB reader budget. Admission follows the available reserved
memory. The query-count limit used by the fixed experiment treats both queries
as one request. Both experiments run the same CPU-bound SELECT. Reservations
are declared resource requirements, and `system.query_log` records actual query
memory.

When concurrent reservations exhaust the reader budget, SELECTs wait for capacity.
If capacity remains unavailable after `workload_admission_timeout_ms`, the server
returns `MEMORY_RESERVATION_ACQUISITION_TIMEOUT`. The queue has capacity for every
SELECT scheduled in the run, preventing queue length from becoming a separate
rejection policy. A reservation larger than the workload budget fails with
`RESOURCE_LIMIT_EXCEEDED`. The request timeline records each error reason.
Scheduler accounting grows above the initial reservation when actual tracked
memory exceeds it. Growth can evict a running query. Eviction and other execution
failures are counted as failed requests.

INSERTs reserve 16 MiB each in a writer workload with a 64 MiB budget. A shared
parent budget covers the reader budget plus the writer budget. The existing
32-query server limit and the per-query memory limits also apply.

```sh
just experiment protect-writes-memory read_memory_mib=0 / read_memory_mib=64
```

The experiment samples reader reserved memory and pending allocations from
`system.scheduler` every 20 ms, as well as admitted requests from
`system.processes`. Sampled peaks can miss shorter states. The scheduler's
admission and rejection counters are saved with each run. Workloads and the
resource are removed after traffic drains, including on interruption. Existing
lab data and saved results are retained. This experiment requires a lab with
no pre-existing RESOURCE or WORKLOAD objects and leaves those objects untouched
if it finds them.

The **Workload activity** column opens a graph for the named reader or writer
workload. Reserved memory uses the left axis and pending reservations use the
right axis. Completed requests stack upward from zero on the MiB axis. Their
block heights represent declared reservation sizes. Execution failures confirmed
by `ExceptionWhileProcessing` remain in this stack and are coloured red.
Rejected demand stacks directly above the admitted requests on the same MiB
axis. Attempts with unconfirmed execution appear separately. Older saved runs
can also contain unsent attempts.

Hovering a request shows its requested reservation, sampled reserved memory and
headroom, and any recorded rejection reason. Blocks use client request intervals.
Resource values come from scheduler samples. The separate **Request timeline**
column retains the SELECT and INSERT view.

Selecting a request opens its details. The shared readout reports reserved
memory, pending reservations and requests overlapping the replay cursor.
Sample timestamps identify the observations used. Brief changes between samples
can be missed, and a reservation can fail to fit even when part of the budget
is free. Scheduler memory accounting includes each query's reservation floor
and any tracked memory above that floor.

Memory reservation scheduling is experimental in ClickHouse. Its behavior is
documented in [workload memory reservations](https://clickhouse.com/docs/operations/workload-scheduling#memory-reservations).
CPU workload limits control thread allocation and throttling and could be
explored in a separate experiment.
