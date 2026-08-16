"""Populate two monthly partitions, then shorten the TTL as a staged rollout.

The point of the sequence is what does *not* happen at step 2: with
`materialize_ttl_after_modify = 0` the ALTER only rewrites the table
definition, so the existing parts keep the TTL metadata of the old policy and
no historical data is removed. Step 3 then applies the new policy to one
chosen month, leaving the other month on the old policy until an operator
decides to continue.
"""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")

# Each month lands in its own part. Both are years older than the 30-day policy
# introduced below, so both would be removed by an immediate materialization.
ch.command(
    "INSERT INTO demo.events (event_time, id, payload) VALUES "
    "('2025-01-15 09:00:00', 1, 'january-a'), "
    "('2025-01-15 09:01:00', 2, 'january-b'), "
    "('2025-01-15 09:02:00', 3, 'january-c')"
)
ch.command(
    "INSERT INTO demo.events (event_time, id, payload) VALUES "
    "('2025-02-15 09:00:00', 4, 'february-a'), "
    "('2025-02-15 09:01:00', 5, 'february-b'), "
    "('2025-02-15 09:02:00', 6, 'february-c')"
)
print("inserted January 2025 (partition 202501) and February 2025 (partition 202502)")

# Step 1: change the policy without materializing it. The default (`1`) would
# start applying the new 30-day rule to every existing part immediately.
ch.command(
    "ALTER TABLE demo.events MODIFY TTL event_time + INTERVAL 30 DAY DELETE",
    settings={"materialize_ttl_after_modify": 0},
)
print("changed the TTL to 30 days without materializing it for existing parts")

# Step 2: roll the new policy out to January only. This is a mutation, so it
# rewrites that month's parts and drops its expired rows now, rather than
# waiting for a background TTL merge.
ch.command(
    "ALTER TABLE demo.events MATERIALIZE TTL IN PARTITION 202501",
    settings={"mutations_sync": 2},
)
print("materialized the new TTL in January 2025 only")
print("February 2025 still carries the TTL metadata of the previous policy")
