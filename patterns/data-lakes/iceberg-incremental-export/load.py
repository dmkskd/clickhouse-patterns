"""Insert two batches of events and force a refresh after each one."""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")


def refresh():
    # Deterministic demonstration control: production waits for the
    # one-minute schedule instead of forcing the refresh.
    ch.command("SYSTEM REFRESH VIEW demo.order_events_to_iceberg")
    ch.command("SYSTEM WAIT VIEW demo.order_events_to_iceberg")


ch.command(
    "INSERT INTO demo.order_events VALUES "
    "(1, '2026-10-20 10:00:00', 100, 'created', 'IT', 40.00), "
    "(2, '2026-10-20 10:00:05', 101, 'created', 'DE', 15.50), "
    "(3, '2026-10-20 10:01:00', 100, 'paid', 'IT', 40.00), "
    "(4, '2026-10-20 10:02:00', 102, 'created', 'FR', 99.90)"
)
refresh()
print("batch 1: 4 events inserted and exported")

ch.command(
    "INSERT INTO demo.order_events VALUES "
    "(5, '2026-10-20 10:03:00', 101, 'paid', 'DE', 15.50), "
    "(6, '2026-10-20 10:04:00', 102, 'cancelled', 'FR', 99.90), "
    "(7, '2026-10-20 10:05:00', 100, 'shipped', 'IT', 40.00)"
)
refresh()
print("batch 2: 3 events inserted; the refresh appends only these")
