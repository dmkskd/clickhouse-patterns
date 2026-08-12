"""Versioned upsert from S3: deduplicate and apply corrections by version, keyed.

Each row carries a `version` that increases with recency. The target is
ReplacingMergeTree(version), so the highest version per id wins. This shows the
shape PeerDB uses (its _peerdb_version, a nanosecond sync time):

  batch 1 (version 1): 1000 events
  batch 2 (version 2): corrects ids 0..99 to 'refund'
  re-load batch 1:     cannot overwrite the corrections, because 1 < 2

The version travels with the row in the staged file, so re-loading a file is
idempotent and order-independent.
"""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")
KEY, SECRET, FMT = "clickhouse", "clickhouse_secret", "Parquet"


def s3(name):
    return f"s3('http://minio:9000/clickhouse/events/{name}', '{KEY}', '{SECRET}', '{FMT}')"


def stage(name, select):
    ch.command(f"INSERT INTO FUNCTION {s3(name)} {select}")


def load(name):
    ch.command(f"INSERT INTO demo.events SELECT id, kind, version FROM {s3(name)}")


# batch 1: 1000 events at version 1
stage("batch-001.parquet",
      "SELECT number AS id, ['click', 'view', 'purchase'][number % 3 + 1] AS kind, toUInt64(1) AS version FROM numbers(1000)")
load("batch-001.parquet")
print("loaded batch 1 (version 1): 1000 events")

# batch 2: corrects the first 100 ids to 'refund' at version 2
stage("batch-002.parquet",
      "SELECT number AS id, 'refund' AS kind, toUInt64(2) AS version FROM numbers(100)")
load("batch-002.parquet")
print("loaded batch 2 (version 2): corrected ids 0..99 to 'refund'")

# re-load the OLD batch 1 (version 1). It cannot overwrite the version-2
# corrections; ReplacingMergeTree keeps the highest version per id.
load("batch-001.parquet")
print("re-loaded batch 1; the version-2 corrections survive")
