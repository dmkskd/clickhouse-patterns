"""Insert one expired part and one current part, then let DELETE TTL act.

Do not use MATERIALIZE TTL here: it creates a mutation and would rewrite data,
which would obscure the whole-part DELETE TTL behaviour this pattern verifies.
"""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")

# The two event months form separate parts. Only the older one is past the
# table's single 30-day retention period.
ch.command(
    "INSERT INTO demo.events "
    "(event_time, batch, id, payload) VALUES "
    "('2000-01-15 00:00:00', 'expired', 1, 'expired-a'), "
    "('2000-01-15 00:01:00', 'expired', 2, 'expired-b'), "
    "('2100-01-15 00:00:00', 'current', 3, 'kept-a'), "
    "('2100-01-15 00:01:00', 'current', 4, 'kept-b')"
)
print("inserted one expired part and one current part")
print("background DELETE TTL is configured to check every second for this demonstration")
