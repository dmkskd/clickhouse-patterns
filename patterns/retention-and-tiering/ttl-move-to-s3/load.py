"""Insert hot and cold partitions, then materialize the configured move TTL."""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")

# The old rows form their own monthly part. The volume sets
# perform_ttl_move_on_insert=0, so this demonstrates the TTL move rather than
# moving synchronously as part of INSERT.
ch.command(
    "INSERT INTO demo.tiered_events VALUES "
    "('2000-01-15 00:00:00', 1, 'old-a'), "
    "('2000-01-15 00:01:00', 2, 'old-b'), "
    "(now(), 3, 'hot-a'), "
    "(now(), 4, 'hot-b')"
)
print("inserted one expired and one current monthly partition on the hot volume")

# Deterministic demonstration control: production normally lets the background
# mover perform this work after a part becomes eligible.
ch.command("ALTER TABLE demo.tiered_events MATERIALIZE TTL")
print("materialized TTL; the expired part is eligible for cold_s3")
