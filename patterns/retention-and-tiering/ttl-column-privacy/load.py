"""Insert expired sensitive fields while retaining useful event dimensions."""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")
ch.command(
    "INSERT INTO demo.access_events "
    "(event_time, id, status, client_ip, user_agent) VALUES "
    "('2000-01-15 00:00:00', 1, '200', '192.0.2.10', 'ExampleBrowser/1.0'), "
    "('2000-01-15 00:01:00', 2, '404', '192.0.2.11', 'ExampleBrowser/1.0')"
)
print("inserted two expired events with IP addresses and user-agent strings")
print("background column TTL is configured to check every second for this demonstration")
