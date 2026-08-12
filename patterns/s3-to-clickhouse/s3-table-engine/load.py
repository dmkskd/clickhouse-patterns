"""The S3 table engine: a declared table over an S3 prefix, read and written.

Two objects are already in S3 under exports/ before ClickHouse is involved. The
reader table covers the prefix with a glob; the writer table is bound to a single
key, because a glob cannot name the object an INSERT would create. Inserting
through the writer makes the new rows visible to the reader, which is how the
original and appended data end up in one query.

The default write is create-only: a second INSERT into an existing key fails
until s3_create_new_file_on_insert or s3_truncate_on_insert says what to do
instead.
"""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")
KEY, SECRET, FMT = "clickhouse", "clickhouse_secret", "Parquet"


def s3(path):
    return f"s3('http://minio:9000/clickhouse/{path}', '{KEY}', '{SECRET}', '{FMT}')"


# Two objects land in the bucket before any ClickHouse table exists.
for n in range(1, 3):
    lo = (n - 1) * 1000
    ch.command(
        f"INSERT INTO FUNCTION {s3(f'exports/existing-{n:03d}.parquet')} "
        f"SELECT number + {lo} AS id, ['click', 'view', 'purchase'][number % 3 + 1] AS kind "
        "FROM numbers(1000)"
    )
print("staged 2 existing objects (2000 rows) under exports/")

# The reader table sees them immediately: the table is a declaration, not a copy.
print("exports_s3 reads:", ch.query("SELECT count() FROM demo.exports_s3").result_rows[0][0])

# Writing goes through the single-key table. This creates exports/appended.parquet.
ch.command("INSERT INTO demo.exports_write SELECT number + 2000 AS id, 'refund' AS kind FROM numbers(500)")
print("wrote 500 rows to exports/appended.parquet")

# The reader's glob now matches three objects, so the original and appended rows
# are returned by one query.
print("exports_s3 reads:", ch.query("SELECT count() FROM demo.exports_s3").result_rows[0][0])

# A second write to the same key fails: the engine only ever creates objects.
try:
    ch.command("INSERT INTO demo.exports_write SELECT number AS id, 'ignored' AS kind FROM numbers(10)")
    raise AssertionError("expected the second INSERT into an existing key to fail")
except AssertionError:
    raise
except Exception as exc:
    print("second INSERT rejected, as expected:", str(exc).splitlines()[0][:120])

# s3_create_new_file_on_insert writes a new object (appended.1.parquet) instead
# of refusing, so repeated exports to one declaration are possible.
ch.command(
    "INSERT INTO demo.exports_write SELECT number + 2500 AS id, 'refund' AS kind FROM numbers(500) "
    "SETTINGS s3_create_new_file_on_insert = 1"
)
print("wrote 500 more rows to a new object via s3_create_new_file_on_insert")

# The reader's glob now covers four objects: the two staged and the two written.
print("exports_s3 reads:", ch.query("SELECT count() FROM demo.exports_s3").result_rows[0][0])
