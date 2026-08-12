"""Bulk load from S3 with the s3() table function, the documented one-line import.

An orchestrator stages three Parquet files under events/, and ClickHouse loads
them all in one INSERT using a glob (events/*.parquet). A glob reads every
matching file, which is how the s3() function scales from one file to a batch.
"""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")
KEY, SECRET, FMT = "clickhouse", "clickhouse_secret", "Parquet"


def s3(path):
    return f"s3('http://minio:9000/clickhouse/{path}', '{KEY}', '{SECRET}', '{FMT}')"


# Stage three files, each 1000 events, under events/ in S3.
for n in range(1, 4):
    lo = (n - 1) * 1000
    ch.command(
        f"INSERT INTO FUNCTION {s3(f'events/batch-{n:03d}.parquet')} "
        f"SELECT number + {lo} AS id, ['click', 'view', 'purchase'][number % 3 + 1] AS kind "
        "FROM numbers(1000)"
    )
print("staged 3 files (3000 rows) under events/ in S3")

# One INSERT loads all three files via a glob. This is the documented bulk load.
ch.command(f"INSERT INTO demo.events SELECT id, kind FROM {s3('events/*.parquet')}")
print("loaded events/*.parquet into demo.events (3000 rows)")
