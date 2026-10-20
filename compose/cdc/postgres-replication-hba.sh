#!/bin/sh
# Permit physical replication connections from the Compose network
# (walshadow base backup + WAL streaming). Logical slots don't need this.
set -eu
echo "host replication all all scram-sha-256" >> "$PGDATA/pg_hba.conf"
