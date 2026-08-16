"""Insert an expired hour of detail and two recent request measurements."""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")

# One old hour becomes a single rollup row. A separate current insert remains
# as detailed data because its seven-day TTL has not expired.
ch.command(
    "INSERT INTO demo.hourly_request_metrics "
    "(event_time, service, bytes) VALUES "
    "('2000-01-01 00:01:00', 'api', 120), "
    "('2000-01-01 00:15:00', 'api', 300), "
    "('2000-01-01 00:50:00', 'api', 80)"
)
ch.command(
    "INSERT INTO demo.hourly_request_metrics "
    "(event_time, service, bytes) VALUES "
    "('2100-01-01 12:01:00', 'api', 110), "
    "('2100-01-01 12:10:00', 'api', 140)"
)
print("inserted three expired request measurements in one hour")
print("inserted two current request measurements that remain detailed")
print("background GROUP BY TTL is configured to check every second for this demonstration")
