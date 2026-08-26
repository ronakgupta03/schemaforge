#!/usr/bin/env bash
# Start both MCP servers that TrueForge connects to (localhost:8001, localhost:8002).
set -uo pipefail
cd "$(dirname "$0")/.."

# load .env
if [ -f .env ]; then set -a; . ./.env; set +a; fi
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5433/bookstore}"

.vevn/bin/python -m pip install -q -r mcp-servers/postgres-mcp/requirements.txt 2>/dev/null \
  || uv pip install --python .vevn/bin/python -q -r mcp-servers/postgres-mcp/requirements.txt

echo "[postgres-mcp] starting on :8001"
.vevn/bin/python mcp-servers/postgres-mcp/server.py &
PG_PID=$!

echo "[github-mcp] starting on :8002 (uvx first run may take a minute)"
GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:?set in .env}" \
  uvx --from git+https://github.com/GongRzhe/Github-MCP-Server \
  github-mcp-server --transport http --port 8002 &
GH_PID=$!

wait