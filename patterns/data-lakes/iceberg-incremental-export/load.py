"""Insert two batches of events and force a refresh after each one."""
from pattern_explorer.orchestration.nodes import connect

ch = connect("ch")


def check_drift(stage, stage_name):
    ch.command(
        "INSERT INTO demo.drift_check "
        f"SELECT {stage}, '{stage_name}', * FROM demo.lake_drift"
    )


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
check_drift(1, "after export")
print("stage 1: source and Iceberg compared")

# Change exported rows in the source. The next refresh selects no rows: the
# cursor is past both rows, and an update or delete does not change a row's
# _block_number or _block_offset.
ch.command("UPDATE demo.order_events SET amount = 45.00 WHERE event_id = 1")
ch.command("DELETE FROM demo.order_events WHERE event_id = 2")
refresh()
print("updated event 1 and deleted event 2 in the source; the refresh exported nothing")
check_drift(2, "after update and delete")
print("stage 2: source and Iceberg compared")
