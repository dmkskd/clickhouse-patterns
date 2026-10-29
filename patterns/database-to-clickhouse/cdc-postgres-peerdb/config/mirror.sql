-- Apply edits with: just reload
-- sync_interval is the CDC batch timeout in seconds (upstream default: 10).
-- This demo retains its existing 1-second override; use 10 for the upstream default.
CREATE MIRROR IF NOT EXISTS two_table_mirror
FROM postgres_source TO clickhouse_target
WITH TABLE MAPPING (
    public.orders:orders,
    public.orders_existing:orders_existing
)
WITH (
    do_initial_copy = true,
    sync_interval = 1
);
