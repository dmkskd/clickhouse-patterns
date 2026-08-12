# Translating patterns into agent skills

> **Status: partially implemented.** The repository now provides the shared
> [clickhouse-pattern-lab](../../skills/clickhouse-pattern-lab/SKILL.md) workflow
> skill plus project adapters for Codex and Claude. The generated thematic
> skills and per-pattern rule files proposed below have not been implemented.

## Reference format

[ClickHouse/agent-skills](https://github.com/ClickHouse/agent-skills) is the
official skills repo. A skill is a directory under `skills/<name>/` with:

- `SKILL.md`: frontmatter (`name`, `description`, `license`, `metadata` with
  author and version) plus a body describing when to use it and pointing to rules.
  The `description` is written as a trigger, for example "MUST USE when reviewing
  ClickHouse schemas ...".
- `README.md`, `metadata.json`.
- `rules/`: individual `.md` files, one validated rule each, cited in responses
  as "Per `rule-name` ...".

Skills provide ClickHouse-specific guidance that an agent can consult before
answering.

## How the patterns map to skills

Each runnable pattern records its SQL, expected results, and constraints found
during implementation. An agent rule can refer to that tested example instead
of maintaining separate, unverified guidance.

The following constraints were identified while implementing and testing the
patterns:

- `LEFT JOIN` fills unmatched String columns with `''`, not `NULL`, so `coalesce`
  does not fire (from the transitions pattern).
- A producer Kafka table still needs `kafka_group_name`.
- A refreshable MV must use `APPEND` when the target is a Kafka table; the default
  replace mode cannot work on a Kafka engine.
- `KeeperMap` needs `keeper_map_path_prefix`, or the connector's exactly-once
  state table fails to create.
- The Altinity sink connector's bundled clickhouse-jdbc cannot parse ClickHouse
  26.x responses; pin a known-good server version.
- A `DELETE WHERE` TTL rewrites all surviving rows in the part, repeatedly, so
  cost scales with what survives (from the TTL proposal).

## Proposed mapping

Group patterns by theme into skills, one rule per pattern:

- `clickhouse-kafka-ingestion`: rules from the pull, push-connect, exactly-once,
  produce, and refreshable-MV patterns.
- `clickhouse-sharded-kafka-ingestion`: rules from the three
  `kafka-ingest-sharded-*` workarounds.
- `clickhouse-cdc`: rules from the MySQL and Postgres CDC patterns.
- `clickhouse-retention-ttl`: rule from the TTL pattern.

Each rule should state when it applies, describe the SQL and known constraints,
and link to the runnable pattern used to verify it. The pattern READMEs already
contain much of this information.

## Generation

Generate skill files from the pattern metadata and documentation to reduce
duplication. A script could scaffold a `SKILL.md` and per-pattern `rules/*.md`
from each pattern's `pattern.yaml` (title, profiles) and `README.md` (technique
and constraints). Regenerate the files when a pattern changes.

## Open questions

- Granularity: one skill per pattern, or skills grouped by theme?
- Upstream: contribute to ClickHouse/agent-skills, or keep a local skills set.
- Sync: should rule text be generated from each pattern's README, or maintained
  separately?
