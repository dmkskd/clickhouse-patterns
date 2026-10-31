# Resource limits and admission control (new group proposal)

**Status:** Outstanding. Draft for discussion.

ClickHouse has many independent mechanisms that limit connections,
concurrency, memory, CPU, IO, and usage over time. They are configured at
different scopes, were added across many releases, and react differently at
the limit. This group would map each mechanism to its scope and its behavior
at the limit, with runnable patterns that show each behavior.

Proposed group: `resource-limits`, title "Resource limits & admission control".

Sources: ClickHouse source at 26.10 (`Settings.cpp`, `ServerSettings.cpp`,
`MergeTreeSettings.cpp`, `ProcessList.cpp`, `ErrorCodes.cpp`), the English docs
in the same tree, and the changelogs for 24.1 to 26.10. Versions below are the
release that introduced the behavior.

**Behavior at the limit:**

- **wait:** queued, starts or continues later
- **reject:** fails before execution starts
- **throttle:** runs slower
- **downscale:** runs with fewer threads
- **spill:** moves state to disk and continues
- **break:** stops early and returns a partial result (`*_overflow_mode = 'break'`)
- **kill:** fails while running
- **warn:** row in `system.warnings` only

## Admission sequence for one query

1. **Connection.** `max_connections` (server, default 4096) refuses the
   connection. `min/max_os_cpu_wait_time_ratio_to_drop_connection` (server)
   drops a new connection with a probability that grows with the CPU wait/busy
   ratio. `tcp_close_connection_after_queries_num` / `_seconds` closes a TCP
   connection: `TCP_CONNECTION_LIMIT_REACHED`, and the query that triggered it
   does not run.
2. **Session.** `max_sessions_for_user` (profile only): `USER_SESSION_LIMIT_EXCEEDED`.
3. **Early memory check (26.2).** If server memory is already above the
   limit, the query is rejected before authentication with
   `MEMORY_LIMIT_EXCEEDED`. Users in `users_to_ignore_early_memory_limit_check`
   skip it.
4. **Async table loading.** A query that needs a table still loading at
   startup (`async_load_databases`) waits. Server `max_waiting_queries` caps
   how many wait: `SERVER_OVERLOADED` (24.3).
5. **Workload admission** (only when a `QUERY` or `MEMORY RESERVATION`
   resource exists). The query waits for a query slot and a memory
   reservation. `workload_admission_timeout_ms` (26.9, default 0 = no limit)
   bounds the wait: `QUERY_SLOT_ACQUISITION_TIMEOUT` /
   `MEMORY_RESERVATION_ACQUISITION_TIMEOUT`. Workload `max_waiting_queries`
   rejects with `SERVER_OVERLOADED`. Waiting queries are not in
   `system.processes`.
6. **Process list** (`ProcessList::insert`, in this order):
   1. server `max_concurrent_queries`: waits up to `queue_max_wait_ms`, then
      `TOO_MANY_SIMULTANEOUS_QUERIES`; rejects at once when `queue_max_wait_ms = 0`
   2. server `max_concurrent_insert_queries`, `max_concurrent_select_queries`: reject
   3. `max_concurrent_queries_for_all_users`: reject
   4. `max_concurrent_queries_for_user`: reject

   Only step 1 waits. Internal queries, `KILL QUERY`, async insert flushes and
   `system.processes` reads skip all four.
7. **Probabilistic overload rejection (25.4).** `min/max_os_cpu_wait_time_ratio_to_throw`
   (query settings): `SERVER_OVERLOADED` with a probability interpolated
   from the CPU wait/busy ratio.
8. **Quota.** Checked at start and while reading: `QUOTA_EXCEEDED` until the
   interval resets.
9. **Execution.** CPU slots, memory limits, complexity limits, throttles
   (tables below).

## Mechanisms by scope

### Server (`config.xml`)

| Setting | At the limit | Error / signal | Notes |
|---|---|---|---|
| `max_concurrent_queries` | wait (`queue_max_wait_ms`), then reject | `TOO_MANY_SIMULTANEOUS_QUERIES` | Code default 0, shipped `config.xml` sets 1000. Counts non-internal queries only (`QueryNonInternal` metric, 26.2) |
| `max_concurrent_select_queries`, `max_concurrent_insert_queries` | reject | `TOO_MANY_SIMULTANEOUS_QUERIES` | |
| `max_waiting_queries` | reject | `SERVER_OVERLOADED` | Async table loading only (24.3) |
| `max_connections` | refuse connection | | |
| `concurrent_threads_soft_limit_num`, `_ratio_to_cores` | downscale | `ConcurrencyControl*` events | Each query gets at least one thread. Code default for ratio was 0 until 26.5 (shipped config: 2). Ignored once a CPU workload resource exists |
| `concurrent_threads_scheduler` | slot distribution policy | | `round_robin`, `fair_round_robin` (default 25.8), `max_min_fair` (26.1, default 26.2) |
| `concurrent_threads_lazy_allocation` | | | 26.6: a query requests slots on demand instead of `max_threads` up front |
| `max_server_memory_usage`, `_to_ram_ratio` | kill (allocating query or overcommit victim) | `MEMORY_LIMIT_EXCEEDED`, `GlobalMemoryLimitExceeded` (26.6) | Since 26.6 the ratio is recomputed at runtime from available host or cgroup memory (`memory_worker_dynamic_hard_limit`) |
| `memory_worker_*` | | | Tracker correction from RSS/cgroup (26.10), speculative RSS reserve (26.7) |
| `merges_mutations_memory_usage_soft_limit`, `_to_ram_ratio` (0.5) | new merges not scheduled | profile event (25.10) | Running merges continue |
| `max_*_bandwidth_for_server` (merges, mutations, local/remote read/write, replicated fetches/sends, backups) | throttle | `*ThrottlerSleepMicroseconds` | |
| `background_pool_size`, `background_*_pool_size` | background work waits | | |
| `max_table_num_to_throw`, `max_database_num_to_throw`, ... `_to_warn` | reject DDL / warn | | |
| `cpu_slot_preemption`, `cpu_slot_quantum_ns`, `cpu_slot_preemption_timeout_ms`, `cpu_slot_parking` | | | Workload CPU only. Preemption default on since 26.1 |
| `throw_on_unknown_workload` | reject | `RESOURCE_ACCESS_DENIED` | 25.2. With `false`, an unknown workload bypasses scheduling |

### User and settings profile

Set in a settings profile or on the user, and locked with constraints (`min`,
`max`, `disallowed`, `const`, `changeable_in_readonly`; violation:
`SETTING_CONSTRAINT_VIOLATION`).

| Setting | At the limit | Error |
|---|---|---|
| `max_concurrent_queries_for_user` | reject (no wait) | `TOO_MANY_SIMULTANEOUS_QUERIES` |
| `max_concurrent_queries_for_all_users` | reject (no wait) | `TOO_MANY_SIMULTANEOUS_QUERIES` |
| `max_memory_usage_for_user` | kill, or overcommit wait then kill | `MEMORY_LIMIT_EXCEEDED` |
| `max_sessions_for_user` | reject session | `USER_SESSION_LIMIT_EXCEEDED` |
| `max_network_bandwidth_for_user`, `_for_all_users` | throttle | Also remote filesystem IO since 26.5 |
| `max_temporary_data_on_disk_size_for_user` | kill | |

### Query (settings, usually fixed in a profile)

| Setting | At the limit | Error |
|---|---|---|
| `max_memory_usage` | kill, or spill first via `max_bytes_(ratio_)before_external_{group_by,sort,join,distinct,set}` | `MEMORY_LIMIT_EXCEEDED` |
| `memory_overcommit_ratio_denominator(_for_user)`, `memory_usage_overcommit_max_wait_microseconds` | wait up to 5 s for memory, then the most overcommitted query is killed | `MEMORY_LIMIT_EXCEEDED` |
| `max_threads` | caps parallelism | |
| `max_threads_min_free_memory_per_thread` (26.5, 1 GiB) | downscale under server memory pressure | |
| `use_concurrency_control_for_max_threads` (26.10) | plans with the fair share of CPU slots when `max_threads` is auto | |
| `max_execution_time`, `max_estimated_execution_time` | `timeout_overflow_mode`: kill or break | `TIMEOUT_EXCEEDED` |
| `max_rows/bytes_to_read`, `_leaf` variants, `max_result_rows/bytes`, `max_rows_to_group_by`, `max_rows_in_set/join/distinct`, `max_rows_to_transfer`, ... | `*_overflow_mode`: kill or break; `group_by_overflow_mode = 'any'` stops adding keys | `TOO_MANY_ROWS`, `TOO_MANY_ROWS_OR_BYTES`, ... |
| `min_execution_speed(_bytes)` | kill after `timeout_before_checking_execution_speed` | `TOO_SLOW` |
| `max_execution_speed(_bytes)`, `max_network_bandwidth`, `max_local/remote_*_bandwidth` | throttle | |
| `max_partitions_per_insert_block` | reject insert or warn | `TOO_MANY_PARTS` |
| `priority`, `low_priority_query_wait_time_ms` | lower-priority queries pause while higher-priority ones run | |
| `min/max_os_cpu_wait_time_ratio_to_throw` | reject with probability | `SERVER_OVERLOADED` |

### Quotas (`CREATE QUOTA`)

Usage over an interval, keyed by user, IP (optionally a subnet), forwarded IP,
client key, or normalized query hash (26.4).

- Resources: `queries`, `query_selects`, `query_inserts`, `errors`,
  `result_rows/bytes`, `read_rows/bytes`, `written_bytes`, `written_rows`
  (26.10), `execution_time`, `failed_sequential_authentications` (24.2),
  `queries_per_normalized_hash` (26.4).
- At the limit: reject until the interval resets (`QUOTA_EXCEEDED`).
  `read_rows` can stop a running query.
- Counted per server: a distributed query is charged on the initiator only,
  and counters reset on restart.
- Before 26.6, only one of several quotas assigned to a user was enforced,
  chosen non-deterministically. Since 26.6 all of them apply.

### Workloads (`CREATE RESOURCE`, `CREATE WORKLOAD`)

Off until a resource exists. Limits apply per host. A query selects a leaf
workload with `SETTINGS workload = '...'`, normally fixed by a profile
constraint. Merges and mutations use `merge_workload` / `mutation_workload`
(IO only; CPU and memory are not scheduled for them).

| Resource (since) | Workload settings | At the limit |
|---|---|---|
| IO: `READ/WRITE DISK d`, `ANY DISK` (24.11 SQL) | `max_io_requests`, `max_bytes_inflight`, `max_bytes_per_second`, `max_burst_bytes` | wait / throttle |
| CPU: `MASTER THREAD`, `WORKER THREAD` (25.4) | `max_concurrent_threads(_ratio_to_cores)` | wait for slots, downscale |
| CPU throttling (25.8) | `max_cpus`, `max_cpu_share`, `max_burst_cpu_seconds` | throttle; needs `cpu_slot_preemption` |
| Query slots: `QUERY` (25.6) | `max_concurrent_queries`, `max_queries_per_second`, `max_burst_queries` | wait; bounded by `workload_admission_timeout_ms` (26.9) |
| Query slots (25.7) | `max_waiting_queries` | reject, `SERVER_OVERLOADED`; leaf workloads only |
| Memory: `MEMORY RESERVATION` (26.6, experimental) | `max_memory`, `precedence`, query `reserve_memory` | wait for reservation; higher precedence evicts (kills) lower |
| Memory spill (26.10, experimental) | `max_memory_before_spill`, `max_memory_to_spill_ratio` | spill |
| Ordering | `priority` (CPU/IO), `precedence` (memory), `weight`, `scheduler` = `fifo` / `fair` / `las` / `priority` (26.10) with query `weight`, `workload_priority`, `weight_lowering_*` | no limit |

Other workload facts: definitions are stored on disk or in Keeper
(`workload_zookeeper_path`), can be defined in `config.xml`
(`resources_and_workloads`, 25.10), and several root workloads may coexist
(26.10).

### Table (MergeTree settings, insert side)

| Setting | At the limit | Error |
|---|---|---|
| `parts_to_delay_insert` (1000) / `max_delay_to_insert` | throttle insert | |
| `parts_to_throw_insert` (3000), `max_parts_in_total`, `inactive_parts_to_throw_insert` | reject insert | `TOO_MANY_PARTS` |
| `number_of_mutations_to_delay` / `_to_throw` | throttle / reject mutation | `TOO_MANY_MUTATIONS` |

### ClickHouse Cloud

`max_concurrent_queries_for_all_users` defaults to 1000, and `max_memory_usage`
scales with replica RAM. Service limits (1000 queries per replica, parts,
tables) are soft guardrails. Compute-compute separation (warehouses) isolates
workloads across services. XML quotas are not supported; quotas must be
created with DDL.

## Documentation gaps and traps

These are the points the group intro and pattern READMEs should state, because
the docs do not, or contradict themselves:

1. **Two settings named `max_waiting_queries`.** The server setting counts
   queries waiting for async table loading. The workload setting caps the
   workload query queue. Neither applies to server `max_concurrent_queries`.
   This is the confusion in the support thread that prompted this proposal.
2. **`queue_max_wait_ms` applies only to server `max_concurrent_queries`.**
   Its description says "if the number of concurrent requests exceeds the
   maximum" and does not say that the per-kind and per-user limits reject
   without waiting.
3. **Workload waits are bounded since 26.9.** The workload page still says
   blocked queries "wait indefinitely" and does not mention
   `workload_admission_timeout_ms`.
4. **Stale statement in the workload CPU section:** "A separate logic should
   be used to limit the number of concurrent queries and it is not currently
   supported for workloads." The `QUERY` resource has existed since 25.6.
5. **Preemption default.** "Threads vs CPUs" reads as if `cpu_slot_preemption`
   is off by default. It has been on since 26.1.
6. **CPU resource disables `concurrent_threads_soft_limit_*`.** This is
   mentioned only in a note.
7. **Three different priorities:** query `priority` (ProcessList pause),
   workload `priority` (CPU/IO between workloads), query `workload_priority`
   (inside a workload with `scheduler = 'priority'`).
8. **Defaults differ between code and shipped config:**
   `max_concurrent_queries` is 0 in code and 1000 in `config.xml`.
   `concurrent_threads_soft_limit_ratio_to_cores` was 0 in code until 26.5.
9. **`max_server_memory_usage_to_ram_ratio` is not static since 26.6.** The
   limit follows host or cgroup available memory.
10. **Quota scope:** per server, charged on the initiator, reset on restart.
    Before 26.6, only one of several assigned quotas was enforced.
11. **Queries waiting for workload admission are not in `system.processes`**
    and do not count towards `max_concurrent_queries`.

## Observability

- `system.query_log`: `exception_code`, `query_duration_ms`, `ProfileEvents`
  (`ConcurrencyControl*`, `ConcurrentQueryWaitMicroseconds`,
  `*ThrottlerSleepMicroseconds`, `SchedulerIO*WaitMicroseconds`, `QueryPreempted`).
- `system.metrics`: `Query`, `QueryNonInternal`, `ConcurrencyControlSoftLimit`,
  `ConcurrencyControlAcquired`.
- `system.scheduler`, `system.workloads`, `system.resources`.
- `system.quotas`, `system.quota_limits`, `system.quota_usage`.
- `system.warnings` (CPU and memory overload, object counts).
- `system.events`: `GlobalMemoryLimitExceeded`, `QueryMemoryLimitExceeded`.

## Candidate patterns

Each pattern saturates one limit with a load script and asserts the outcome in
`verify.sql` from `system.query_log` (exception code, duration) and the events
above.

1. **Server concurrency: wait vs reject.** `max_concurrent_queries` with
   `queue_max_wait_ms = 0` and `> 0`, next to `max_concurrent_select_queries`
   and `max_concurrent_queries_for_user`, which reject at once.
2. **User limits in settings profiles.** Two users with memory, time and
   concurrency limits locked by constraints; `SETTING_CONSTRAINT_VIOLATION`
   when a user tries to raise them.
3. **Overflow modes.** `throw` vs `break` for read, result, and time limits.
4. **Quotas.** Interval quota keyed by user, `QUOTA_EXCEEDED`, reset; keyed by
   normalized query hash.
5. **Memory: limits, overcommit, spilling.** Which query is killed at the
   server limit; spilling with the `max_bytes_ratio_before_external_*` settings.
6. **CPU slots without workloads.** `concurrent_threads_soft_limit_num`
   downscaling instead of rejecting.
7. **Workloads: query slots.** Interactive vs batch workloads, separate
   `max_concurrent_queries`, `max_waiting_queries`, `workload_admission_timeout_ms`.
8. **Workloads: CPU and IO sharing.** `priority` and `weight` between two
   workloads under contention; `system.scheduler`.
9. **Workloads: memory reservation.** `reserve_memory` queueing and
   precedence eviction (experimental, 26.6+).
10. **Insert backpressure.** `parts_to_delay_insert` delay, then `TOO_MANY_PARTS`.

The group intro holds the admission sequence and a condensed scope table.
Each pattern links back to its row.

## Open questions

- Version pin: patterns 7 to 9 need 26.9+ (admission timeout) or 26.6+
  (memory reservation).
- Whether insert backpressure (10) and background pools belong here or in the
  ingestion groups.
- Whether the Cloud section stays in the intro or becomes its own pattern
  (warehouses).
- Not checked: whether the overload connection drop and
  `tcp_close_connection_*` work over HTTP.

## References

- [Workload scheduling](https://clickhouse.com/docs/operations/workload-scheduling)
- [Quotas](https://clickhouse.com/docs/operations/quotas)
- [Restrictions on query complexity](https://clickhouse.com/docs/operations/settings/query-complexity)
- [Constraints on settings](https://clickhouse.com/docs/operations/settings/constraints-on-settings)
- [Settings profiles](https://clickhouse.com/docs/operations/settings/settings-profiles)
- [Memory overcommit](https://clickhouse.com/docs/operations/settings/memory-overcommit)
- [Server overload](https://clickhouse.com/docs/operations/settings/server-overload)
- [TCP connection limits](https://clickhouse.com/docs/operations/settings/tcp-connection-limits)
- [Cloud usage limits](https://clickhouse.com/docs/cloud/bestpractices/usage-limits)
- [`ProcessList.cpp`](https://github.com/ClickHouse/ClickHouse/blob/master/src/Interpreters/ProcessList.cpp)
- [Changelog 2026](https://github.com/ClickHouse/ClickHouse/blob/master/CHANGELOG.md),
  [2025](https://clickhouse.com/docs/whats-new/changelog/2025),
  [2024](https://clickhouse.com/docs/whats-new/changelog/2024)
