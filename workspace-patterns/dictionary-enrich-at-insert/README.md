# Dictionary enrichment at insert time

> ⚠️ **Demo pattern. Not for use.**

Profiles: `single`, `postgres`. Driver: `ch`.

A dictionary holds the customer dimension in ClickHouse memory and reloads it
from Postgres on `LIFETIME` expiry. One definition then serves two designs that
differ only in when `dictGet` runs.

```text
public.customers --[LIFETIME reload]--> test.customers_dict (HASHED, in memory)
                                              |            |
                       dictGet at insert -----'            '----- dictGet at read
                                              |                        |
INSERT -> test.events_raw --[MV]--> test.events_enriched      test.events_current_tier
                                    (tier stored, frozen)     (tier resolved per SELECT)
```

## The two designs

| | at insert (MV → table) | at read (view) |
|---|---|---|
| Where the attribute lives | a stored column | nowhere |
| Value returned | the dimension as of insert | the dimension as it is now |
| Read cost | single-table scan | a lookup per row scanned |
| ORDER BY on the attribute | possible | not possible |
| Effect of a source correction | none on existing rows | applies to the whole history |

The choice follows what the column means. A tier an order was priced under is
part of the fact and belongs in the enriched table. A customer's country, after
a data fix, is a current description of the entity and belongs in the view.

## What the run shows

`load.py` inserts events 1-3, promotes customer 1 from `gold` to `platinum` in
Postgres, waits for the dictionary to reload, then inserts event 4 for the same
customer. `verify.sql` reads customer 1's events both ways: `STORED` gives event
1 `gold` and event 4 `platinum`, while `CURRENT` gives both `platinum`.

The interval between the `UPDATE` and the reload is a staleness window on the
write path. An event inserted inside it is enriched with the previous tier and
keeps it, which is why the reload interval is part of the design rather than a
tuning detail.

## Operational notes

`LIFETIME(MIN 1 MAX 2)` is a test setting. Each expiry re-reads the whole
dimension, so a real deployment picks an interval against source load, or adds
an `invalidate_query` so a reload happens only when the source changed.

A `dictGet` on a key the dictionary does not hold returns the attribute type's
default, not an error, so an unknown `customer_id` is stored as `''`. Where that
would be indistinguishable from real data, `dictHas` gates the lookup.

`HASHED` keeps every element resident on every node that uses the dictionary.
`system.dictionaries` reports `status`, `element_count`, and `bytes_allocated`;
when the dimension outgrows memory, `SPARSE_HASHED` trades CPU for size and
`CACHE` trades a miss latency for a bounded footprint.

## Run

```bash
just test dictionary-enrich-at-insert
```
