"""Insert DEBUG and INFO logs with different retention periods."""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")

# One INSERT deliberately creates one mixed part. DEBUG rows are already past
# their one-day retention period; INFO rows remain within their seven-day period.
ch.command(
    "INSERT INTO demo.variable_retention_events "
    "(event_time, log_level, id, payload) "
    "SELECT now() - INTERVAL 2 DAY, 'DEBUG', 1, 'debug-a' "
    "UNION ALL SELECT now() - INTERVAL 2 DAY, 'DEBUG', 2, 'debug-b' "
    "UNION ALL SELECT now(), 'INFO', 3, 'info-a' "
    "UNION ALL SELECT now(), 'INFO', 4, 'info-b'"
)
print("inserted DEBUG and INFO logs in one part")
print("background DELETE TTL is configured to check every second for this demonstration")
