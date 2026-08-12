# Reading and writing a bucket prefix with the S3 table engine

Profiles: `single`, `s3`. Driver: `ch`.

The [`s3()` table function](../s3-bulk-load/) reads a path once, inside a single
statement. The [`S3` table engine](https://clickhouse.com/docs/engines/table-engines/integrations/s3)
binds that same access to a table name, so the path, credentials, and format are
declared once and every later query refers to the table. The table holds no data
of its own, and each `SELECT` reads the objects in the bucket.

```
upstream writer --> S3: exports/*.parquet <--INSERT-- demo.exports_write (S3, one key)
                            |
                    demo.exports_s3 (S3, glob) --> reader
```

## Objects that were already there

`load.py` puts two Parquet objects under `exports/` before any ClickHouse table
exists. Declaring the table makes them queryable immediately:

```sql
CREATE TABLE demo.exports_s3 (id UInt64, kind String)
ENGINE = S3('http://minio:9000/clickhouse/exports/*.parquet', ..., 'Parquet');

SELECT count() FROM demo.exports_s3;   -- 2000
```

The glob is what makes one table cover the whole prefix. Files that appear later
are picked up by the next query, because there is no stored state to refresh.

## Writing to the same prefix

An `S3` engine table also writes, but a glob cannot name the object an `INSERT`
would create, so a path containing `*` is read-only. Covering a prefix and
writing to it are therefore two declarations over the same location:

```sql
CREATE TABLE demo.exports_write (id UInt64, kind String)
ENGINE = S3('http://minio:9000/clickhouse/exports/appended.parquet', ..., 'Parquet');

INSERT INTO demo.exports_write SELECT ...;   -- creates exports/appended.parquet
SELECT count() FROM demo.exports_s3;         -- 2500: the original rows and the new ones
```

The write goes to one object and the read covers the prefix, so the original and
appended data come back together from a single query.

## Repeated inserts

A second `INSERT` into `demo.exports_write` fails, because the engine has no way
to append to an object that exists and no merge cycle to consolidate one later.
Two settings decide what happens instead:

- `s3_truncate_on_insert` replaces the object's contents.
- `s3_create_new_file_on_insert` leaves it alone and writes a new object beside
  it (`appended.1.parquet`), which is what `load.py` uses for its second write.

Neither setting produces a single growing file, so repeated exports accumulate
as separate objects and consolidating them is the caller's job.

## When to choose it

Reading through the engine re-reads and re-parses the objects on every query,
with no index and no statistics. It suits a prefix queried occasionally, or a
query result that has to be written back to object storage without introducing
an external tool.

Where the same data is queried repeatedly, importing it into a MergeTree is
worth the copy. The other patterns in this group cover that conversion under
different conditions: a [one-off glob load](../s3-bulk-load/), a
[deduplicating target](../s3-versioned-upsert/) for files that restate earlier
rows, and [S3Queue](../s3queue-unordered/) when new files should be imported as
they arrive.

```bash
just test s3-table-engine
```

## Reference

- [ClickHouse: S3 table engine](https://clickhouse.com/docs/engines/table-engines/integrations/s3)
- [ClickHouse: Integrating S3 with ClickHouse](https://clickhouse.com/docs/integrations/s3)
