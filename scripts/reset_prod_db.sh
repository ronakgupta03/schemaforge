#!/usr/bin/env bash
# Reset the "production" bookstore DB to a clean pre-split state, then re-seed.
#
# Drops and recreates the database (wiping alembic_version + every table), then
# runs scripts/seed_prod.sh to apply the 0001 baseline and seed 200,000 users /
# 5,000 books. Use this before a demo take, or whenever `alembic upgrade head`
# fails with "Can't locate revision identified by '<n>'" because the DB is still
# stamped at a migration that was reverted out of demo-app/alembic/versions.
#
# Usage:
#   bash scripts/reset_prod_db.sh
#   DATABASE_URL=postgresql://user:pass@host:5433/bookstore bash scripts/reset_prod_db.sh
#
# Safe to re-run: it terminates live connections to the target DB first, so the
# postgres-mcp server (and any open sandbox) simply reconnect on demand.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5433/bookstore}"
if [ -x "$REPO/.vevn/bin/python" ]; then PY="$REPO/.vevn/bin/python"; else PY=python3; fi

echo "resetting database for $DATABASE_URL ..."
"$PY" - "$DATABASE_URL" <<'PY'
import sys
import urllib.parse

import psycopg

url = sys.argv[1]
p = urllib.parse.urlsplit(url)
dbname = p.path.lstrip("/")
# DROP/CREATE DATABASE cannot run in a transaction and cannot target the DB we
# are connected to, so connect to the 'postgres' maintenance database.
admin = urllib.parse.urlunsplit((p.scheme, p.netloc, "/postgres", p.query, ""))

conn = psycopg.connect(admin, autocommit=True)
conn.execute(
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
    "WHERE datname = %s AND pid <> pg_backend_pid()",
    (dbname,),
)
conn.execute(f'DROP DATABASE IF EXISTS "{dbname}"')
conn.execute(f'CREATE DATABASE "{dbname}"')
conn.close()
print(f"  dropped + recreated '{dbname}' (connected via '/postgres')")
PY

echo "re-seeding (0001 baseline + data) ..."
exec bash scripts/seed_prod.sh
