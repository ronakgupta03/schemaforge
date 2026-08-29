#!/usr/bin/env bash
# Seed the "production" bookstore DB (docker, port 5433) with the pre-split
# schema and 200,000 users / 5,000 books so EXPLAIN ANALYZE is meaningful.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5433/bookstore}"
if [ -x "$REPO/.vevn/bin/alembic" ]; then ALEMBIC="$REPO/.vevn/bin/alembic"; else ALEMBIC=alembic; fi
if [ -x "$REPO/.vevn/bin/python" ]; then PY="$REPO/.vevn/bin/python"; else PY=python3; fi

echo "applying alembic baseline (0001)..."
(cd "$REPO/demo-app" && DATABASE_URL="$DATABASE_URL" "$ALEMBIC" upgrade head)

echo "seeding..."
(cd "$REPO/demo-app" && DATABASE_URL="$DATABASE_URL" "$PY" seed.py 200000 5000)

echo "row counts:"
PGPASSWORD=postgres psql -h 127.0.0.1 -p 5433 -U postgres -d bookstore -Atc "SELECT 'users='||count(*) FROM users" || \
  "$PY" -c "import psycopg,os; print(psycopg.connect(os.environ['DATABASE_URL']).execute('SELECT count(*) FROM users').fetchone())"