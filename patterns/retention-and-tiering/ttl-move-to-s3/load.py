"""Insert hot and cold partitions, then materialize the configured move TTL."""
from datetime import datetime, timezone

from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")

# The old rows form their own monthly part. The volume sets
# perform_ttl_move_on_insert=0, so this demonstrates the TTL move rather than
# moving synchronously as part of INSERT.
ch.command(
    "INSERT INTO demo.tiered_events VALUES "
    "('2000-01-15 00:00:00', 1, 'old-a'), "
    "('2000-01-15 00:01:00', 2, 'old-b')"
)
print("inserted one expired monthly partition on the hot volume")

# The current-month rows land as two inserts, then OPTIMIZE consolidates them
# into one part. The merge is forced rather than left to the background merger
# for the same reason the TTL move is materialized: the demonstration must be
# deterministic. The hot partition thus shows ordinary merge activity, in
# contrast to the cold partition, which moves whole and is never rewritten.
ch.command("INSERT INTO demo.tiered_events VALUES (now(), 3, 'hot-a')")
ch.command("INSERT INTO demo.tiered_events VALUES (now(), 4, 'hot-b')")
current_month = datetime.now(timezone.utc).strftime("%Y%m")
ch.command(f"OPTIMIZE TABLE demo.tiered_events PARTITION '{current_month}' FINAL")
print("inserted the current monthly partition as two parts, then merged them")

# Deterministic demonstration control: production normally lets the background
# mover perform this work after a part becomes eligible.
ch.command("ALTER TABLE demo.tiered_events MATERIALIZE TTL")
print("materialized TTL; the expired part is eligible for cold_s3")
