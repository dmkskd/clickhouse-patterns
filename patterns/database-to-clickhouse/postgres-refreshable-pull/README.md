# Refreshable MV pull from Postgres: scheduled full replace

Profiles: `single`, `postgres`. Driver: `ch`.

Level 2 of this group. One DDL statement on top of the level-1 declaration, with
no connector, replication slot, or orchestrator.

```text
public.orders ---- full SELECT once per tick ------> test.pg_orders (declaration)
 (live Postgres)                                            |
                                        REFRESH EVERY 5 SECOND
                                                            v
                                        test.orders (MergeTree, replaced whole)
                                                            |
                                          plain SELECT, no FINAL -> readers
```

## The mechanism

```sql
CREATE MATERIALIZED VIEW test.orders
REFRESH EVERY 5 SECOND
ENGINE = MergeTree ORDER BY id
AS SELECT ... FROM test.pg_orders;   -- the level-1 PostgreSQL engine table
```

On each tick ClickHouse reruns that `SELECT` and atomically replaces the whole
table with the result. `APPEND` is deliberately not used.

Five seconds is a test-speed choice rather than a recommendation; a production
deployment refreshes every minute or few minutes. The interval controls how
stale the copy is allowed to get and nothing else.

A full replace is lighter than CDC because it never reconstructs anything.
Reconstructing current state
from a stream of changes requires a `ReplacingMergeTree`, a `_version` column to
order competing rows, an `is_deleted` tombstone to represent a removal, and
`FINAL` on every read to collapse them. A full replace never holds two versions
of a row, and a row deleted in Postgres is simply absent from the next result,
so `verify.sql` is a plain `SELECT ... ORDER BY id`.

The transformation is equally cheap, because `upper(customer)`, the
`Decimal(12, 2)` cast, and the derived `amount_band` sit in the view's `SELECT`
and are evaluated during the refresh. The CDC patterns need a separate materialized view and an
explicit snapshot backfill for the same result, because their rows arrive one
change at a time.

## The staleness window

`load.py` prints the staleness directly:

```text
applied INSERT/UPDATE/DELETE to public.orders in Postgres
pass-through read sees 3 rows; the refreshed copy still sees 3
waiting for the next scheduled refresh
```

The pass-through table already reflects Postgres; the refreshed copy will not
until the next scheduled run. Whether that gap is acceptable is the decision
between this pattern and CDC.

The schedule is inspectable at any time:

```sql
SELECT view, status, last_refresh_time, next_refresh_time, exception
FROM system.view_refreshes;

SYSTEM REFRESH VIEW test.orders;   -- force one now
```

A failed refresh leaves the previous result in place and the next run retries,
so a Postgres outage presents as staleness rather than as a broken table.

## Where it breaks

The pattern suits any table small enough that re-reading all of it costs less
than tracking what changed, such as dimensions, configuration, and lookups.

Cost scales with table size rather than with change volume. Re-reading a
million-row table on every tick to pick up four changed rows is wasteful, and it
is a periodic scan on the OLTP side as well. Three signals indicate the limit:

1. the source table is too large to re-read in full on the interval;
2. the staleness window is too wide;
3. the intermediate values are needed, not just the current state, which a full
   replace never observes.

Signal 1 has a cheaper answer than CDC. If the source carries a monotonic
`updated_at` or id, `REFRESH EVERY ... APPEND` with a watermark predicate pulls
only new rows and removes the full-scan cost while keeping the connector-free
property. Deletes must then be handled explicitly, because appended rows
accumulate and the target returns to `ReplacingMergeTree`. This works well for insert-heavy tables and badly for
mutable ones, which is where CDC begins to justify its extra services.

## A dictionary may be the better fit

If the target is a small keyed lookup rather than a scanned table, a dictionary
sourced directly from Postgres can replace this whole pattern. It holds the rows
in memory, refreshes on a `LIFETIME`, and supports `invalidate_query` to skip the
reload entirely when a cheap check shows nothing changed, which this pattern has
no equivalent of, since every refresh here re-reads every row unconditionally.

A dictionary is queryable as an ordinary table, so the choice is not about SQL
versus `dictGet`, but about the target. A dictionary is memory-resident and
keyed by a `PRIMARY KEY`, while this pattern produces a MergeTree on disk
with a primary index, skip indexes, and projections available, holding the result
of an arbitrary query that can join against other ClickHouse tables.

## The same shape with MySQL

Only the level-1 declaration changes; the view is unchanged:

```sql
CREATE TABLE test.my_orders (id Int32, customer String, amount Int32)
ENGINE = MySQL('mysql:3306', 'test', 'orders', 'root', 'root');
```

## Run

```bash
just test postgres-refreshable-pull
```

The test waits for a scheduled refresh rather than forcing one with
`SYSTEM REFRESH VIEW`, so the convergence it asserts is the real schedule.
