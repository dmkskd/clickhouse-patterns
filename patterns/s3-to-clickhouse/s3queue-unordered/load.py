"""Drop files into the bucket S3Queue watches; unordered mode ingests any file.

Unordered mode tracks the set of processed files in Keeper, so it ingests every
new file regardless of name order, including files that arrive out of lexical
order. This loader drops three files and lets ClickHouse process them.
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
print("dropped 3 files into queue/; S3Queue unordered processes each exactly once")
