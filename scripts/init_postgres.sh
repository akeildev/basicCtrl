#!/usr/bin/env bash
# One-time provisioning for the cua-maximalist Postgres backend.
#
# Prerequisite:
#   brew install postgresql@16
#   brew services start postgresql@16
#
# Trust model (T-1-02): the connection string `postgresql://localhost:5432/cua_maximalist`
# carries NO embedded credentials. Local Postgres uses peer authentication for
# the local user. There are no secrets to leak.
#
# Idempotent — safe to re-run; createdb is a no-op if the database exists.

set -euo pipefail

DB_NAME="${DB_NAME:-cua_maximalist}"

if ! command -v psql >/dev/null 2>&1; then
  echo "psql not on PATH. Run 'brew install postgresql@16' first." >&2
  exit 1
fi

# Default invocation provisions: createdb cua_maximalist
if ! psql -lqt | cut -d \| -f 1 | grep -qw "$DB_NAME"; then
  echo "Creating database $DB_NAME..."
  createdb "$DB_NAME"
else
  echo "Database $DB_NAME already exists (skipping createdb)."
fi

echo "Provisioning LangGraph PostgresSaver tables..."
uv run python scripts/init_postgres.py

echo "Done. Verify with: psql $DB_NAME -c '\\dt'"
