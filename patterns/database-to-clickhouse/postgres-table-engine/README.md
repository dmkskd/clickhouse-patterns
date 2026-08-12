# Postgres table engine: query in place, no copy

Profiles: `single`, `postgres`. Driver: `ch`.

Level 1 of this group. Nothing is replicated or stored and there is no pipeline
to operate: ClickHouse holds a declaration of where the Postgres table is and
resolves it on every read.

```text
                                    ClickHouse
public.orders --+-> test.orders_table_engine  (table engine)     -+
 (live Postgres)+-> pg_schema.orders          (database engine)  +-> SELECT -> client
                `-> postgresql(...)           (table function)   -'
```

Data moves in one direction here, out of Postgres and into a ClickHouse query.
The `PostgreSQL` table engine is also writable, so `INSERT INTO
test.orders_table_engine` would write rows back into Postgres. That is
deliberately outside this pattern and absent from the diagram, which covers the
database-to-ClickHouse read path only.

## The three access paths

The difference between the first two is who defines the schema, and when:

| | table engine | database engine |
|---|---|---|
| Statements | one `CREATE TABLE` per source table | one `CREATE DATABASE` for all of them |
| Column types | declared locally, with the mapping chosen | inferred by ClickHouse at query time |
| New table in Postgres | invisible until DDL is written for it | queryable immediately |
| Source schema changes | the table breaks on the next read | followed automatically |

**Table engine.** `CREATE TABLE ... ENGINE = PostgreSQL(host, db, table, user,
password)`. One ClickHouse table bound to one Postgres table, with the column
types declared on the ClickHouse side. Because that declaration is local, a type
can be widened or a `LowCardinality` pinned, and the object is stable enough to
grant on. Use it for a table queried often and presented on deliberate terms.

**Database engine.** `CREATE DATABASE pg_schema ENGINE = PostgreSQL(...)` maps
the whole schema in one statement. Nothing is declared per table, so names and
types resolve when a query runs, so the mapping tracks the source and a table added in
Postgres needs no ClickHouse DDL. Use it for exploration and for schemas that
change often. The cost is that the types are no longer a local choice, and a
source change reaches the queries unannounced.

**Table function.** `postgresql('postgres:5432', 'test', 'orders', ...)` inline in
the query, creating no object and needing no DDL or grant. Use it for one-off reads
and inside `INSERT INTO ... SELECT` when seeding a local table by hand.

`verify.sql` reads all three and returns identical rows, because all three do the
same thing.

## What it costs

`load.py` applies an `INSERT`, an `UPDATE`, and a `DELETE` directly to
`public.orders`, then reads ClickHouse again. The new row is present, the updated
amount is 250, and the deleted row is gone on the very next `SELECT`.

The CDC patterns in this group reach the same three results only by adding a
`ReplacingMergeTree`, a version column, a tombstone, and `FINAL` on every read.
None of that applies here, because no second copy exists to disagree with the
first.

The cost sits on the other side of the wire. Every ClickHouse query becomes a
Postgres query. Rows arrive row-oriented and are discarded after the query, so
compression, the primary index, skip indexes, and projections contribute nothing.
Only the filters and projections ClickHouse can translate are pushed down;
anything else transfers rows and filters locally. A dashboard pointed at this is
pointed at production Postgres.

## The same shape with MySQL

Everything above holds for MySQL, with `MySQL` in place of `PostgreSQL`:

```sql
CREATE TABLE test.my_orders (id Int32, customer String, amount Int32)
ENGINE = MySQL('mysql:3306', 'test', 'orders', 'root', 'root');

CREATE DATABASE my ENGINE = MySQL('mysql:3306', 'test', 'root', 'root');

SELECT * FROM mysql('mysql:3306', 'test', 'orders', 'root', 'root');
```

The `mysql` compose profile in this repository serves the same seeded
`test.orders`, so those statements run as written against it. The pattern is not
duplicated for MySQL because the decision it documents is identical.

## When to leave

Move to [postgres-refreshable-pull](../postgres-refreshable-pull/) when the read
load grows heavy, or when the source rows should sit in a MergeTree so they
can be indexed, compressed, and joined cheaply. Move to
[cdc-mysql-clickhouse](../cdc-mysql-clickhouse/) or
[cdc-postgres-peerdb](../cdc-postgres-peerdb/) when the table is too large to
re-read on a schedule, or when sub-minute freshness is required.

## Run

```bash
just test postgres-table-engine
```
