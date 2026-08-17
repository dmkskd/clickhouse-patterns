# Fault injection and recovery procedures

## Motivation

Every pattern runs one path: bring the stack up clean, load, converge, compare
output. Nothing exercises what happens when a node dies mid-ingest, and nothing
records how to get the pattern unstuck afterwards.

That second gap is the more valuable one. The common failure report for
distributed ClickHouse is not a wrong answer, it is "it's stuck" — a replica that
never catches up, a distributed DDL query that never returns, a Kafka consumer
that stops committing. The remedy circulating in issue threads and support chats
is usually a Keeper edit: remove the stale entry under `/clickhouse/task_queue/ddl`
or the abandoned replica path, then restart the node. That knowledge is oral
tradition. It is not in the docs of the pattern it applies to, it is untested
against any particular topology, and it is the kind of instruction that destroys
data when applied to the wrong pattern.

A pattern library is the right place to fix that, because the recovery procedure
depends entirely on the architecture. "Drop the replica path from Keeper" is
routine for a full-copy shard that can re-read the whole topic, and is data loss
for a partition-affinity shard that owns the only copy of its partitions.

The `tradeoffs` blocks already make recovery claims that nothing checks. From
`kafka-ingest-sharded-partition-affinity`:

> Partition ownership is deterministic, so recovery can reset offsets for just
> the affected shard's partitions.

That is a testable statement written as prose.

## What does not transfer

The idea comes from [Antithesis](https://antithesis.com/docs/reference/dependencies/),
whose whole product is fault injection. Their *setup* model is worth copying;
their *assertion* model is not. Antithesis is a deterministic hypervisor that
replays exact thread schedules, so it can assert on precise output under fault.
This harness runs real Docker with real wall clocks and real Kafka rebalance
timers.

This matters concretely for the existing `verify` step. Kill a shard mid-ingest
in `kafka-ingest-sharded-full-copy` and the consumer group rebalances: the
survivor picks up the dead shard's partitions, replays from the last committed
offset, and the physical row count per shard becomes timing-dependent. A
`verify.sql` that produced a stable `expected.txt` on the happy path may not
under fault, and the pattern fails for reasons that are not the pattern's fault.

So scenarios need invariant assertions, not golden-file comparison:

- a count that must never decrease,
- a uniqueness property that must hold whatever the interleaving,
- a final state that must match the happy-path result even though the path differed.

The existing `Expectation` model already fits this, which is the lucky part.
`wait_for` (`orchestration/runner.py:112`) polls until a query equals a value
rather than reading once, so "the pattern reconverges after the fault" is
expressible with the model as it stands — the same `ready_when` block, evaluated
again after the perturbation.

## Proposed capability: a `scenarios` section

Add an optional `scenarios` list to `pattern.yaml`. Each scenario runs after
`load`, perturbs the stack, optionally applies a recovery procedure, and asserts
invariants. Patterns without the section behave exactly as they do now.

```yaml
scenarios:
  - name: shard-loss-during-ingest
    description: >-
      Shard 2 dies while the topic is still being consumed. Because every shard
      reads every partition, shard 1 already holds the rows shard 2 was writing;
      the group rebalances and shard 1 continues alone.
    demonstrates: drawback     # ties the scenario to a tradeoffs entry
    fault:
      - action: kill           # compose stop | kill | pause | unpause | start
        target: ch-s2
        after: 2s              # delay from scenario start; omit to fire immediately
    recover:
      - action: start
        target: ch-s2
    invariants:
      - query: "SELECT count() FROM demo.events"
        node: ch-s1
        value: 8000
        timeout: 120
      - query: "SELECT uniqExact(id) FROM demo.events_all"
        node: ch-s1
        value: 8000
        timeout: 120
```

Runner changes:

- A `run_scenario` path alongside `run_pattern`: bring the stack up, apply schema,
  start `load` in the background, apply `fault` steps on their delays, run
  `recover`, then evaluate `invariants` with the existing `wait_for`.
- `fault` and `recover` steps map onto the compose client already in use.
  python-on-whales exposes `compose.stop/kill/pause/unpause/start` on the same
  object `orchestration/stack.py` builds for `up`.
- Scenarios do not run in the default `just test` sweep. They are slower and
  more failure-prone than the happy path, and a flaky scenario must not block
  work on the patterns themselves. Gate them behind an explicit target.

## Keeper surgery as a first-class recovery step

The recovery procedures worth documenting are mostly Keeper edits, so `recover`
needs to express them. Two options:

1. A `keeper` action taking a path and an operation (`rm`, `rmr`, `ls`), executed
   via `clickhouse-keeper-client` in the keeper container.
2. A free-form `script:` pointing at a `.py` or `.sh` in the pattern directory,
   consistent with how `load` already accepts either SQL or Python.

Prefer (1) for the common cases so the procedure stays declarative and greppable
across patterns — the point is that someone hitting "it's stuck" can search the
library for the Keeper path they are staring at and find the pattern it belongs
to. Fall back to (2) for anything more involved.

Paths worth covering, each tied to the pattern where it applies:

- `/clickhouse/task_queue/ddl/<entry>` — a stuck `ON CLUSTER` DDL. Applies to
  every `cluster`, `shards`, and `shards-v2` pattern.
- `/clickhouse/tables/<shard>/<table>/replicas/<replica>` — an abandoned replica
  holding back cleanup. Applies to the `cluster` patterns.
- The StorageKafka2 offset and partition-lock paths — applies to
  `kafka-ingest-sharded-partition-affinity`, and is exactly the claim its
  `tradeoffs` block makes about resetting one shard's offsets.

Each of these should carry the destructive-when-misapplied warning in the
scenario's `description`, since that is what gets rendered.

## Pilot

The two sharded Kafka patterns make opposite trade-offs on precisely the axis a
fault exposes, and both are in the repository now:

- `kafka-ingest-sharded-full-copy` — every shard holds the complete stream.
  Losing a shard costs read and storage amplification but no data; recovery is
  restart and let the group rebalance.
- `kafka-ingest-sharded-partition-affinity` — each shard owns a disjoint set of
  partitions. Losing a shard means nobody is consuming those partitions;
  recovery requires deciding whether to reassign ownership or wait for the node.

Running the same `shard-loss-during-ingest` scenario against both produces the
argument for choosing between them, which no amount of prose in `limitations`
does as well. That comparison is the deliverable; the fault injection is the
easy part.

Note that the partition-affinity pattern runs on `clickhouse-server:head`
(profile `shards-v2`) because StorageKafka2 landed after 26.7. Scenario results
for it are inherently less stable than for the pinned patterns, which is another
reason to keep scenarios out of the default test sweep.

## Sequencing

1. `scenarios` with `fault`, `invariants`, and container-level actions only.
   Enough for the pilot comparison above.
2. `recover`, with the declarative `keeper` action.
3. Rendering — surface scenarios in the explorer next to the `tradeoffs` entry
   each one `demonstrates`, so the drawback and its demonstration read together.
