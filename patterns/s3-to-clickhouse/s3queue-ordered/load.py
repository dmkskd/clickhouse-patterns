"""Drop files into the bucket S3Queue watches; ClickHouse ingests them itself.

Unlike the s3() patterns, nothing here triggers a load. The S3Queue engine polls
the queue/ prefix, processes each new file exactly once (tracking done files in
Keeper), and its materialized view writes the rows into demo.events. This loader
only drops three files into the prefix and lets ClickHouse pull them.
"""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch-s3q")
KEY, SECRET, FMT = "clickhouse", "clickhouse_secret", "Parquet"


def s3(path):
    return f"s3('http://minio:9000/clickhouse/{path}', '{KEY}', '{SECRET}', '{FMT}')"


for n in range(1, 4):
    lo = (n - 1) * 1000
    ch.command(
        f"INSERT INTO FUNCTION {s3(f'queue/batch-{n:03d}.parquet')} "
        f"SELECT number + {lo} AS id, ['click', 'view', 'purchase'][number % 3 + 1] AS kind "
        "FROM numbers(1000)"
    )
print("dropped 3 files into queue/; S3Queue will process each exactly once")
