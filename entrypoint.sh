#!/bin/sh
set -e

if [ ! -f /var/lib/postgresql/data/postgresql.conf ]; then
  echo "Initializing PostgreSQL database..."
  initdb -D /var/lib/postgresql/data
fi

if ! grep -q "shared_preload_libraries = 'timescaledb'" /var/lib/postgresql/data/postgresql.conf; then
  echo "Adding timescaledb to shared_preload_libraries..."
  printf "shared_preload_libraries = 'timescaledb'\n" >> /var/lib/postgresql/data/postgresql.conf
fi

if ! grep -q "listen_addresses = '*'" /var/lib/postgresql/data/postgresql.conf; then
  printf "listen_addresses = '*'\n" >> /var/lib/postgresql/data/postgresql.conf
fi

if ! grep -q "0.0.0.0/0" /var/lib/postgresql/data/pg_hba.conf 2>/dev/null; then
  printf "host all all 0.0.0.0/0 scram-sha-256\n" >> /var/lib/postgresql/data/pg_hba.conf
fi

echo "Starting PostgreSQL..."
exec postgres -D /var/lib/postgresql/data
