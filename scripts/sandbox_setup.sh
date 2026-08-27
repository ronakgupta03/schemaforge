#!/usr/bin/env bash
# Run INSIDE the TrueForge sandbox against the repo checkout at /workspace.
# Sets up: postgres in-sandbox, python venv + deps, baseline schema + 100k seed.
#
# Works both as root (Docker rehearsal) and as a sudo-capable non-root user
# (Daytona default image: uid 1001 'daytona', Debian 13 trixie, PEP 668).
# Prints SANDBOX_READY and writes /workspace/.sfenv-activate.sh for later
# shells to source (venv PATH + DATABASE_URL + TEST_DATABASE_URL).
set -euxo pipefail

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
    SUDO="sudo"
fi

# Run a command as the postgres user: su (root) or sudo -u (non-root).
# The TrueForge-provisioned sandbox starts EMPTY: put the repo at /workspace
# when absent (idempotent for re-runs). /workspace may pre-exist root-owned.
if [ ! -d /workspace/.git ]; then
    if [ -n "$(ls -A /workspace 2>/dev/null)" ]; then
        echo "/workspace exists, is not empty, and has no .git — aborting" >&2
        exit 1
    fi
    $SUDO chown "$(id -u):$(id -g)" /workspace
    git clone --depth 1 https://github.com/ronakgupta03/schemaforge.git /workspace
fi

# Install when the client is missing OR the server is (a client-only image

# Install when the client is missing OR the server is (a client-only image
# passes `command -v psql` but has no cluster under /etc/postgresql).
if ! command -v psql >/dev/null || [ -z "$(ls /etc/postgresql 2>/dev/null)" ]; then
    $SUDO apt-get update -qq
    DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq \
        postgresql postgresql-contrib python3-pip python3-venv
fi

# Resolve AFTER install: on a fresh image /etc/postgresql does not exist yet.
PG_VER=$(ls /etc/postgresql | sort -V | tail -1)

$SUDO service postgresql start || $SUDO pg_ctlcluster "$PG_VER" main start

# Postgres is ready only when TCP accepts connections (alembic/app connect via
# TCP, not the unix socket). Socket-only readiness races the listener.
for i in $(seq 1 60); do
    if run_postgres "pg_isready -h 127.0.0.1 -p 5432 -q"; then
        break
    fi
    sleep 1
done
if ! run_postgres "pg_isready -h 127.0.0.1 -p 5432 -q"; then
    echo "postgres did not become ready on 127.0.0.1:5432" >&2
    exit 1
fi

# Bootstrap via the unix socket: peer auth needs no password, whereas TCP
# (scram) demands one before the postgres superuser has a password set.
run_postgres "psql -c \"ALTER USER postgres PASSWORD 'postgres'\"" || true
run_postgres "createdb bookstore" || true
run_postgres "createdb bookstore_test" || true

cd /workspace

# venv: Debian/Ubuntu mark the system interpreter externally-managed
# (PEP 668), so a bare pip install refuses; a venv also keeps every later
# command (alembic, pytest, pipeline) on one explicit PATH.
python3 -m venv "$HOME/.sfenv"
"$HOME/.sfenv/bin/pip" install --quiet -e core -r demo-app/requirements.txt

export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bookstore
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bookstore_test

(cd demo-app && "$HOME/.sfenv/bin/alembic" upgrade head)
(cd demo-app && "$HOME/.sfenv/bin/python" seed.py 100000 1000)

cat > /workspace/.sfenv-activate.sh <<'EOF'
export PATH="$HOME/.sfenv/bin:$PATH"
export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bookstore
export TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bookstore_test
EOF

echo "SANDBOX_READY"