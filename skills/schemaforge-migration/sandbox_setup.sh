#!/usr/bin/env bash
# Generic in-sandbox bootstrap for SchemaForge on any Postgres-backed repo.
# Reads env (overridable by the target's .sf-sandbox.env). No target-specific literals.
set -euo pipefail

WORK=/workspace; APP="$WORK/app"; VEN="$HOME/.sfenv"; ACT="$HOME/.sfenv-activate.sh"
SF_TOOLING_REPO="${SF_TOOLING_REPO:-https://github.com/ronakgupta03/schemaforge}"

# Ensure /workspace is writable (Daytona ships it root-owned, mode 755).
if [ "$(id -u)" != 0 ] && [ ! -w "$WORK" ]; then sudo chown -R "$(id -u):$(id -g)" "$WORK"; fi

run_postgres() { if [ "$(id -u)" = 0 ]; then su postgres -c "$1"; else sudo -u postgres bash -lc "$1"; fi; }
as_root() { if [ "$(id -u)" = 0 ]; then "$@"; else sudo "$@"; fi; }

# 1. Postgres (install if missing, start, wait for TCP)
if ! command -v psql >/dev/null 2>&1 || [ ! -d /etc/postgresql ]; then
  as_root apt-get update -qq && as_root apt-get install -y -qq postgresql postgresql-contrib
fi
as_root service postgresql start 2>/dev/null || as_root pg_ctlcluster main start 2>/dev/null || true
for _ in $(seq 1 30); do pg_isready -h 127.0.0.1 -p 5432 >/dev/null 2>&1 && break; sleep 1; done
pg_isready -h 127.0.0.1 -p 5432 || { echo "postgres not ready on 5432"; exit 1; }

# 2. Acquire the target repo source into /workspace/app.
#    Private repos: the sandbox has no git credentials and cannot `git clone`;
#    the agent must fetch a tarball via the host-side github MCP
#    (`get_repo_archive`, which holds the token) and extract it here BEFORE
#    running this script. Public repos: a plain `git clone` still works.
if [ -d "$APP" ] && [ -n "$(ls -A "$APP" 2>/dev/null)" ]; then
  : # app source already present (agent extracted it via get_repo_archive)
elif [ -n "${GITHUB_REPO_URL:-}" ]; then
  git clone --depth 1 "$GITHUB_REPO_URL" "$APP" || { echo "git clone failed (private repo? fetch via github get_repo_archive first)"; exit 1; }
else
  echo "no app at $APP: fetch the repo via github MCP get_repo_archive and extract to $APP before running this script"; exit 1
fi
# Local git baseline so `git diff` / `git add -N` work even for a tarball source
# (no remote — never `git fetch` from the sandbox).
{ [ -d "$APP/.git" ] || ( cd "$APP" && git init -q && git add -A && git commit -qm "baseline" ); } 2>/dev/null || true

# 3. Source target profile(s), then auto-detect APP_DIR, then source APP_DIR profile
[ -f "$APP/.sf-sandbox.env" ] && { set -a; . "$APP/.sf-sandbox.env"; set +a; }
if [ -z "${APP_DIR:-}" ]; then
  APP_DIR="$APP"
  for d in "$APP" "$APP"/*/; do [ -f "$d/alembic.ini" ] && { APP_DIR="$d"; break; }; done
fi
APP_DIR="${APP_DIR%/}"
[ -f "$APP_DIR/.sf-sandbox.env" ] && { set -a; . "$APP_DIR/.sf-sandbox.env"; set +a; }

# 4. DB name (default from repo slug)
if [ -z "${SANDBOX_DB_NAME:-}" ]; then
  SANDBOX_DB_NAME="$(basename "${GITHUB_REPO_URL:-app}" .git)"; [ -z "$SANDBOX_DB_NAME" ] && SANDBOX_DB_NAME=appdb
fi
run_postgres "createdb $SANDBOX_DB_NAME" 2>/dev/null || true
run_postgres "createdb ${SANDBOX_DB_NAME}_test" 2>/dev/null || true
DATABASE_URL="postgresql://postgres:postgres@localhost:5432/$SANDBOX_DB_NAME"
TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/${SANDBOX_DB_NAME}_test"

# 5. venv + target deps + schemaforge-core from the tooling repo
[ -x "$VEN/bin/python" ] || python3 -m venv "$VEN"
"$VEN/bin/pip" install -q --upgrade pip
[ -f "$APP_DIR/requirements.txt" ] && "$VEN/bin/pip" install -q -r "$APP_DIR/requirements.txt"
[ -f "$APP/pyproject.toml" ] && "$VEN/bin/pip" install -q "$APP" 2>/dev/null || true
"$VEN/bin/pip" install -q "git+${SF_TOOLING_REPO}#subdirectory=core"

# 6. Migrations (auto-detect tool)
( cd "$APP_DIR" && \
  if [ -f alembic.ini ]; then "$VEN/bin/alembic" upgrade head; \
  elif [ -f manage.py ]; then "$VEN/bin/python" manage.py migrate; \
  else echo "no migration tool in $APP_DIR; skipping baseline"; fi )

# 7. Optional seed
[ -n "${SANDBOX_SEED_CMD:-}" ] && ( cd "$APP_DIR" && PATH="$VEN/bin:$PATH" DATABASE_URL="$DATABASE_URL" eval "$SANDBOX_SEED_CMD" )

# 8. Activate script for later shells
cat > "$ACT" <<EOF
export PATH="$VEN/bin:\$PATH"
export DATABASE_URL="$DATABASE_URL"
export TEST_DATABASE_URL="$TEST_DATABASE_URL"
export APP_DIR="$APP_DIR"
export SANDBOX_DB_NAME="$SANDBOX_DB_NAME"
EOF
echo "SANDBOX_READY db=$SANDBOX_DB_NAME app=$APP_DIR"
