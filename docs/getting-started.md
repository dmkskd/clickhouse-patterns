# Getting started

The repository requires Docker, `uv`, and `just`.

## Setup and discovery

```bash
just setup                        # dependencies + Codex/Claude agent setup
just agent-status                 # verify skill and MCP adapters
just list                         # patterns by category, flow, and topology
just describe                     # what each pattern does
just show kafka-ingest-replicated # files, references, and validation checks
just run kafka-ingest-replicated  # validate, explore, then Enter/Ctrl+C to clean up
```

Each manifest has a short `title`, a structured `graph` that drives the
Explorer architecture, and a longer `description` explaining the trade-offs
and expected behavior. `graph` is the single canonical description of the architecture.
It can also provide external `references` shown before a run.

`just describe` shows the intent for every pattern. Use `just show <pattern>`
for its references, profiles, driver node, files, and validation
checks.

## Workspace patterns

Create a documentation-first company or team pattern without inventing a
runtime:

```bash
just new our-orders-cdc
just diagram our-orders-cdc
```

Or derive an editable copy from a working curated pattern:

```bash
just clone cdc-postgres-peerdb my-orders-cdc
# destination: workspace-patterns/my-orders-cdc/
just run my-orders-cdc
```

To version workspace patterns privately without adding them to this repository,
use a separate Git checkout as the writable root:

```bash
git clone git@github.com:your-org/clickhouse-pattern-workspaces.git ../pattern-workspaces
export CLICKHOUSE_PATTERN_WORKSPACE_DIR="$PWD/../pattern-workspaces"
just clone cdc-postgres-peerdb my-orders-cdc
just list                         # confirms the workspace pattern is discovered
just explore                      # shows it in Pattern Explorer's Workspace group
just run my-orders-cdc
```

`CLICKHOUSE_PATTERN_WORKSPACE_DIR` controls where `just new`, `just clone`, and
`just delete` write, and every command launched with that environment discovers
the root. Persist it in a local shell or `direnv` configuration, then commit the
resulting pattern to the private repository. Static catalogs include the root's
patterns when built with the setting present. `CLICKHOUSE_PATTERN_WORKSPACES`
remains available for discovering additional roots without making them writable.

`just list` shows workspace patterns separately, while `test-all` and pytest
continue to run only the curated `patterns/` library. Commit a workspace to
share it with a team.

Delete a finished experiment with:

```bash
just delete my-orders-cdc
```

Deletion only removes managed workspace entries. It refuses to delete a
library pattern, an unrecognized directory, or the workspace pattern used by
the running session. Finish the foreground `just run`, or use `just stop` for
an advanced detached session, before deleting it.

## Pattern descriptions

Diagrams use one boundary-first vocabulary across every pattern. Ingestion
patterns use `INGESTION: source -> ClickHouse`. Output patterns separate
`INPUT: source -> ClickHouse` from `OUTPUT: ClickHouse -> destination`.
Secondary paths are labelled `QUERY`, `QUERY + DEDUP`, or `TEST ONLY`.

For example, `INGESTION: Kafka -> Kafka Connect -> ClickHouse (MergeTree)`
contrasts with `INGESTION: Kafka -> ClickHouse (Kafka engine -> MV ->
MergeTree)`. Detail lines pair each object name with its role, such as `Kafka
engine table events_in`.

Each pattern describes what it is about:

- `category`: the subject, such as Kafka or CDC
- `flow`: whether data enters ClickHouse (`ingestion`) or leaves it (`output`)
- `topology`: whether ClickHouse is single-node, replicated, or sharded
- `tags`: useful details such as push, pull, or the connector being used

`profiles` specify which services Docker Compose starts for the example.

Before `just run`, `just test`, `just start`, or `just reload` changes
infrastructure, the
Pattern Explorer prints the manifest-derived explanation and execution plan. It then
labels each live phase (`INFRA`, `SCHEMA`, `LOAD`, `WAIT`, `CHECK`, and
`VERIFY`) so the terminal output explains what is happening.

## Explore a validated pattern

`just run` owns the complete foreground lifecycle:

```bash
just run kafka-ingest-replicated
```

It starts the required services, applies the schema, loads the data, waits for
convergence, and compares the verification output. It then prints a `BROWSE`
section with the ClickHouse SQL console (`http://localhost:8123/play`) and
schema visualizer (`http://localhost:8123/schema`) and waits for the user.
Explore through those links, another terminal, MCP, or an agent. Press Enter or
Ctrl+C in the original terminal to remove the containers and volumes. A
reachable environment also remains available after a validation failure so the
failure can be inspected before cleanup.

`just run` requires an interactive terminal. Automation uses:

```bash
just test kafka-ingest-replicated # validate and tear down immediately
just test-all                     # validate every curated pattern
```

Only one running pattern is supported because orchestration reuses a single Compose
project and fixed host ports. The active driver is exposed on `localhost:8123`,
so the read-only
[`mcp-clickhouse`](https://github.com/ClickHouse/mcp-clickhouse) configuration
can remain unchanged while patterns are switched. `just status --json` provides
the same session details for agent workflows.

Use MCP queries to inspect live state, not as a replacement for the pattern
source.

### Codex example

```text
terminal 1$ just run kafka-ingest-replicated
# waits after validation

terminal 2$ codex
> $clickhouse-pattern-lab Inspect the running pattern. Explain its data flow
  and verify both replica row counts. Do not modify ClickHouse.
```

After leaving Codex, return to terminal 1 and press Enter. `just run` tears the
environment down automatically.

### Advanced detached sessions

`just start`, `just status`, `just validate`, `just reload`, and `just stop`
remain available for scripts or agents that cannot own an interactive terminal.
They are not required by the normal user workflow. Detached sessions require an
explicit `just stop`; `just run` does not.

## Agent setup

`just setup` configures the repository's shared Agent Skill for every supported
client after installing Pattern Explorer. The agent step can also be run separately
or limited to one client:

```bash
just agent-setup                  # Codex + Claude
just agent-setup codex            # one client only
just agent-setup claude
just agent-status
```

The canonical skill is
[`skills/clickhouse-pattern-lab/SKILL.md`](../skills/clickhouse-pattern-lab/SKILL.md)
and follows the [Agent Skills specification](https://agentskills.io/specification).
Setup links that one source into each client's repository discovery path:

| Client | Skill adapter | MCP adapter |
|---|---|---|
| Codex | `.agents/skills/clickhouse-pattern-lab` | `.codex/config.toml` |
| Claude Code | `.claude/skills/clickhouse-pattern-lab` | `.mcp.json` |

Both MCP adapters launch the same `mcp-clickhouse` package on demand through
`uv`, connect to `localhost:8123`, and set
`CLICKHOUSE_ALLOW_WRITE_ACCESS=false`. They are project-scoped; setup does not
edit `~/.codex/config.toml` or `~/.claude.json`.

Restart the client after first setup. Codex may ask for the repository to be
trusted; Claude asks for the project MCP server to be approved. With a pattern running, use:

```text
Use $clickhouse-pattern-lab to inspect the running pattern.
```

In Claude Code, `/clickhouse-pattern-lab` is the explicit equivalent. Both
clients can also select the skill automatically from its description.

For another Agent Skills-compatible client, provide its discovery directory:

```bash
just agent-setup --skills-dir "$HOME/.example-agent/skills"
```

This installs the portable skill. MCP client configuration is not standardized,
so other clients still need an adapter for the checked-in
`clickhouse-patterns` MCP registration. `just skill-install` remains as a compatibility
alias for `just agent-setup codex`.

## Find a pattern

Use Pattern Explorer instead of a manually maintained catalog:

```bash
just list                  # compact list grouped by category, flow, and topology
just describe              # diagrams and detailed descriptions
just show <pattern>        # files, references, and validation checks
```

Proposed and implemented follow-up patterns, with background and design notes,
are tracked in
[Outstanding patterns](proposals/outstanding-patterns.md).

For Pattern Explorer internals and instructions for adding a pattern, see
[Pattern Explorer architecture](pattern-explorer.md).
