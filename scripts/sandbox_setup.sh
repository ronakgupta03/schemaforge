#!/usr/bin/env bash
# Run INSIDE the TrueForge sandbox against the repo checkout at /workspace.
# Sets up: postgres in-sandbox, python deps, baseline schema + 100k seed.
set -euxo pipefail

# Install when the client is missing OR the server is (a client-only image
# passes `command -v psql` but has no cluster under /etc/postgresql).
if ! command -v psql >/dev/null || [ -z "$(ls /etc/postgresql 2>/dev/null)" ]; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql postgresql-contrib python3-pip
fi

# Resolve AFTER install: on a fresh image /etc/postgresql does not exist yet.
PG_VER=$(ls /etc/postgresql | sort -V | tail -1)

service postgresql start || pg_ctlcluster "$PG_VER" main start

# Postgres is ready only when TCP accepts connections (alembic/app connect via
# TCP, not the unix socket). Socket-only readiness races the listener.
for i in $(seq 1 60); do
    if su postgres -c "pg_isready -h 127.0.0.1 -p 5432 -q"; then
        break
    fi
    sleep 1
done
if ! su postgres -c "pg_isready -h 127.0.0.1 -p 5432 -q"; then
    echo "postgres did not become ready on 127.0.0.1:5432" >&2
    exit 1
fi

# Bootstrap via the unix socket: peer auth needs no password, whereas TCP
# (scram) demands one before the postgres superuser has a password set.
su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgres'\"" || true
su postgres -c "createdb bookstore" || true
su postgres -c "createdb bookstore_test" || true

cd /workspace
# --break-system-packages: Debian/Ubuntu mark the system interpreter
# externally-managed (PEP 668), so a bare pip install refuses. The sandbox
# is disposable — system site-packages are fine.
python3 -m pip install --quiet --break-system-packages -e core -r demo-app/requirements.txt

export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bookstore
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bookstore_test

(cd demo-app && alembic upgrade head)
(cd demo-app && python seed.py 100000 1000)

echo "SANDBOX_READY"