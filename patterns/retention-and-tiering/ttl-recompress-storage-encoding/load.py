"""Insert old metrics that are eligible for TTL recompression."""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")
ch.command(
    "INSERT INTO demo.recompressed_metrics "
    "(event_time, id, metric_name, value, payload) VALUES "
    "('2000-01-15 00:00:00', 1, 'http_requests', 42.0, repeat('metric payload ', 50)), "
    "('2000-01-15 00:01:00', 2, 'http_requests', 43.0, repeat('metric payload ', 50))"
)
print("inserted two old metric rows eligible for ZSTD recompression")
print("background recompression TTL is configured to check every second for this demonstration")
