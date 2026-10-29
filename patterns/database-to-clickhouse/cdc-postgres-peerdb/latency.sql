-- Source write to ClickHouse insert: updated_at -> ch_inserted_at, in milliseconds.
-- Snapshots, deletes and missing source write times have NULL latency.
-- Freeze NULL in snapshot parts before enabling insert-time defaults.
-- Otherwise old parts could evaluate now64() at read time.
ALTER TABLE test.orders ADD COLUMN ch_inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT NULL;
ALTER TABLE test.orders MATERIALIZE COLUMN ch_inserted_at SETTINGS mutations_sync = 1;
ALTER TABLE test.orders MODIFY COLUMN ch_inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT now64(6, 'UTC');
ALTER TABLE test.orders ADD COLUMN replication_stage LowCardinality(String) DEFAULT if(ch_inserted_at IS NULL, 'Initial snapshot', 'CDC change') AFTER amount;
ALTER TABLE test.orders ADD COLUMN replication_latency_ms Nullable(Float64) DEFAULT if(ch_inserted_at IS NOT NULL AND updated_at > toDateTime64('1970-01-01 00:00:00', 6, 'UTC') AND _peerdb_is_deleted = 0, dateDiff('microsecond', updated_at, ch_inserted_at) / 1000.0, NULL) AFTER amount;
ALTER TABLE test.orders_existing ADD COLUMN ch_inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT NULL;
ALTER TABLE test.orders_existing MATERIALIZE COLUMN ch_inserted_at SETTINGS mutations_sync = 1;
ALTER TABLE test.orders_existing MODIFY COLUMN ch_inserted_at Nullable(DateTime64(6, 'UTC')) DEFAULT now64(6, 'UTC');
ALTER TABLE test.orders_existing ADD COLUMN replication_stage LowCardinality(String) DEFAULT if(ch_inserted_at IS NULL, 'Initial snapshot', 'CDC change') AFTER amount;
ALTER TABLE test.orders_existing ADD COLUMN replication_latency_ms Nullable(Float64) DEFAULT if(ch_inserted_at IS NOT NULL AND updated_at > toDateTime64('1970-01-01 00:00:00', 6, 'UTC') AND _peerdb_is_deleted = 0, dateDiff('microsecond', updated_at, ch_inserted_at) / 1000.0, NULL) AFTER amount;
