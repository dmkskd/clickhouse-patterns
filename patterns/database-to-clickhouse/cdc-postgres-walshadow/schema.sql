-- walshadow creates walshadow.public_orders itself during the initial load;
-- nothing is pre-created in ClickHouse.
CREATE DATABASE IF NOT EXISTS walshadow;
