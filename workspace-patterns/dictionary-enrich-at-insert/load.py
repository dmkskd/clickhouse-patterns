"""Insert events, move a customer between tiers, then insert one more event.

The point of the sequence is the boundary it creates. Events 1-3 are enriched
against the dictionary as loaded; the Postgres dimension then changes; event 4
is enriched after the dictionary has reloaded. The stored tier of an event
therefore depends on when it arrived, while the query-time view reports the
current tier for all of them.
"""
from __future__ import annotations

import psycopg

from pattern_explorer.orchestration.nodes import connect
from pattern_explorer.orchestration.wait import wait_for

ch = connect("ch")

# The dictionary loads lazily on first use; wait for the seeded dimension rather
# than assuming schema.sql already populated it.
wait_for(
    ch,
    "SELECT dictGetString('test.customers_dict', 'tier', toUInt64(1)) = 'gold'",
    1,
    timeout=60,
)
print("dictionary loaded from Postgres: customer 1 is gold")

ch.command(
    """
    INSERT INTO test.events_raw (event_id, customer_id, amount, ts) VALUES
        (1, 1, 100.00, '2026-01-01 00:00:00'),
        (2, 2, 200.00, '2026-01-01 00:00:01'),
        (3, 3, 300.00, '2026-01-01 00:00:02')
    """
)
wait_for(ch, "SELECT count() FROM test.events_enriched", 3, timeout=60)
print("3 events enriched at insert time, customer 1's event stored as gold")

with psycopg.connect(
    host="localhost",
    port=5432,
    user="postgres",
    password="postgres",
    dbname="test",
    autocommit=True,
) as source:
    source.execute("UPDATE customers SET tier = 'platinum' WHERE id = 1")
print("customer 1 promoted to platinum in public.customers")

# Reading the enriched rows now shows what the write path cannot undo: the
# dimension has changed, and the stored copy of it has not.
stored = ch.query(
    "SELECT customer_tier FROM test.events_enriched WHERE event_id = 1"
).result_rows[0][0]
print(f"event 1 still carries the tier it was written with: {stored}")

# LIFETIME(MIN 1 MAX 2) expires within two seconds; nothing reloads a dictionary
# on demand except SYSTEM RELOAD DICTIONARY, which this deliberately avoids.
wait_for(
    ch,
    "SELECT dictGetString('test.customers_dict', 'tier', toUInt64(1)) = 'platinum'",
    1,
    timeout=60,
)
print("dictionary reloaded on LIFETIME expiry: customer 1 is platinum")

ch.command(
    """
    INSERT INTO test.events_raw (event_id, customer_id, amount, ts) VALUES
        (4, 1, 400.00, '2026-01-01 00:00:03')
    """
)
wait_for(ch, "SELECT count() FROM test.events_enriched", 4, timeout=60)
print("event 4 is the same customer, enriched after the change, stored as platinum")
