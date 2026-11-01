# Experiments: on-demand workloads with parameters

Status: **implemented** for the four database CDC patterns. The manifest
format, script contract and measurement rules are documented in
`skills/clickhouse-pattern-author/references/pattern-model.md` ("Experiments");
running them against a session is in `skills/clickhouse-pattern-lab/SKILL.md`.
This file records the design and what is still open.

## Motivation

`load` runs once per pattern start and must finish before `verify`. It cannot
run a workload repeatedly, vary its inputs, or compare results across inputs.
The CDC patterns expose settings in `config/` (walshadow `flush_timeout_ms`,
PeerDB `sync_interval`, Debezium and Altinity `poll.interval.ms`), and their
effect on latency and ClickHouse parts is the question readers ask.

## Design

- **Declared per pattern.** `spec.experiments` names a script in the pattern
  folder, its parameters, the labels and groups of its results, and the group
  order. The script owns the workload; shared pieces live in
  `pattern_explorer/orchestration/probe.py`.
- **Two kinds of parameter.** A `config` parameter rewrites one line of a
  pattern config file and reloads the session; any other parameter is a script
  argument. Values are numbers with an explicit `min`, or a fixed list of
  `choices`.
- **Explicit action.** The Explorer's Experiments panel (shown once the session
  is ready or validated) and `just experiment` start a run. `run`, `reload` and
  `validate` never do. A run takes the session operation slot, so it cannot
  overlap a start, stop or validation.
- **Results outside the session.** One JSON line per completed run in
  `.runtime/experiments/<slug>.jsonl`, so results survive the reloads that a
  config parameter causes. The panel groups columns by pipeline stage, sorts by
  any column, and draws a per-run timeline from the script's `stages`.
- **Config copies, not edits.** A config parameter is written to a copy of the
  file under `.runtime/experiment-config/<slug>/`. The compose overlay mounts
  the copy, and loaders that read `config/` open it through
  `config_overlay.config_file()`. The tracked file never changes, so there is
  no `git diff`, no Explorer page reload and nothing to restore after a crash.
  The session keeps the copies after a run; it reloads only when they change,
  and a normal reload, stop or start drops them.

## Open questions

- **Cost of a config change.** Each changed value reloads the whole session
  (about 15 seconds) and repeats the initial load. Restarting only the service
  that reads the file would be faster, but walshadow keeps its state in the
  container, so a restart still re-snapshots. Per-parameter
  `apply: reload | restart:<service>` is the likely shape.
- **Grids.** A run is one combination of values. Running a grid (every
  combination of two lists) is repeated runs today. The runner side is small
  (expand, order by config values so each copy set loads once, one `batch` id);
  the open part is the UI for entering lists and comparing a batch.
- **Fault experiments.** Choices allow a mode parameter (`restart`, `kill`), and
  text results allow a verdict, but there is no helper yet for stopping or
  restarting a lab service from a script, and no pass/fail column type.
- **Clocks.** Source and ClickHouse run on one host and share its clock. On
  separate hosts the latency columns depend on clock synchronization.
