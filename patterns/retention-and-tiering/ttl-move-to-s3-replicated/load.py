"""Create one old and one current partition, replicate it, then move the old part."""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch-01")

ch.command(
    "INSERT INTO demo.replicated_tiered_events VALUES "
    "('2000-01-15 00:00:00', 1, 'old-a'), "
    "('2000-01-15 00:01:00', 2, 'old-b'), "
    "(now(), 3, 'hot-a'), "
    "(now(), 4, 'hot-b')"
)
print("inserted two old and two current rows on ch-01; Keeper will copy both parts to ch-02")

# The cold volumes defer move-on-insert. Running this ON CLUSTER means each
# replica materializes its local old part and writes its own S3 object set.
ch.command("ALTER TABLE demo.replicated_tiered_events ON CLUSTER patterns MATERIALIZE TTL")
print("materialized MOVE TTL on both replicas; each old part is eligible for cold_s3")
