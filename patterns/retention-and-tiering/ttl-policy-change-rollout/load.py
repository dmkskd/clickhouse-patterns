"""Populate two monthly partitions, then shorten the TTL one month at a time.

Both months are older than the new 30-day policy and younger than the one-year
policy the table starts with, so nothing is expired until the change is
materialized. The dates are computed from the current date rather than
hardcoded, which keeps that window true whenever the pattern runs.

The point of the sequence is what does *not* happen at step 2: with
`materialize_ttl_after_modify = 0` the ALTER only rewrites the table
definition, so the existing parts keep the TTL metadata of the old policy and
no historical data is removed. Step 3 then applies the new policy to one
chosen month.
"""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")

# Two months inside the 30-day to one-year window, far enough from either edge
# that the pattern does not depend on the day it runs.
OLD_MONTH_DAYS = 150
RECENT_MONTH_DAYS = 120

old_month, recent_month = ch.query(
    "SELECT toYYYYMM(now() - INTERVAL %(old)s DAY), "
    "       toYYYYMM(now() - INTERVAL %(recent)s DAY)",
    parameters={"old": OLD_MONTH_DAYS, "recent": RECENT_MONTH_DAYS},
).first_row

# Each month lands in its own part, which is what makes a partial rollout
# possible: a partition is the unit MATERIALIZE TTL can be pointed at.
ch.command(
    "INSERT INTO demo.events (event_time, id, payload) "
    "SELECT now() - INTERVAL %(old)s DAY + number * 60, number + 1, 'older-month' "
    "FROM numbers(3)",
    parameters={"old": OLD_MONTH_DAYS},
)
ch.command(
    "INSERT INTO demo.events (event_time, id, payload) "
    "SELECT now() - INTERVAL %(recent)s DAY + number * 60, number + 4, 'recent-month' "
    "FROM numbers(3)",
    parameters={"recent": RECENT_MONTH_DAYS},
)
print(f"inserted partitions {old_month} (older month) and {recent_month} (recent month)")

# Step 1: change the policy without materializing it. The default (`1`) would
# start applying the new 30-day rule to every existing part immediately.
ch.command(
    "ALTER TABLE demo.events MODIFY TTL event_time + INTERVAL 30 DAY DELETE",
    settings={"materialize_ttl_after_modify": 0},
)
print("changed the TTL from one year to 30 days without materializing it")

# Step 2: roll the new policy out to the older month only. This is a mutation,
# so it rewrites that month's parts and drops its expired rows now, rather than
# waiting for a background TTL merge.
ch.command(
    f"ALTER TABLE demo.events MATERIALIZE TTL IN PARTITION {old_month}",
    settings={"mutations_sync": 2},
)
print(f"materialized the new TTL in partition {old_month} only")
print(f"partition {recent_month} still carries the deadline of the one-year policy")
