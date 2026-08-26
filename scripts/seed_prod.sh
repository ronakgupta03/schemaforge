#!/usr/bin/env bash
# Seed the "production" bookstore DB (docker, port 5433) with the pre-split
# schema and 200,000 users / 5,000 books so EXPLAIN ANALYZE is meaningful.
set -euo pipefail
cd "$(dirname "$0")/.."

export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5433/bookstore}"

echo "applying alembic baseline (0001)..."
(cd demo-app && DATABASE_URL="$DATABASE_URL" .vevn/bin/alembic upgrade head 2>/dev/null \
  || (cd demo-app && DATABASE_URL="$DATABASE_URL" alembic upgrade head))

echo "seeding..."
(cd demo-app && DATABASE_URL="$DATABASE_URL" .vevn/bin/python seed.py 200000 5000)

echo "row counts:"
psql "$DATABASE_URL" -Atc "SELECT 'users='||count(*) FROM users" || \
  .vevn/bin/python -c "import psycopg,os; print(psycopg.connect(os.environ['DATABASE_URL']).execute('SELECT count(*) FROM users').fetchone())"