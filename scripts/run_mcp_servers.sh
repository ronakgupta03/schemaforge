#!/usr/bin/env bash
# Start both MCP servers that TrueForge connects to (localhost:8001, localhost:8002).
set -uo pipefail
cd "$(dirname "$0")/.."

# load .env
if [ -f .env ]; then set -a; . ./.env; set +a; fi
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5433/bookstore}"

export SF_MCP_CONFIG_TOKEN="${SF_MCP_CONFIG_TOKEN:-$(openssl rand -hex 24)}"
printf '%s\n' "$SF_MCP_CONFIG_TOKEN" > .sf-mcp-token
chmod 600 .sf-mcp-token

# install deps (pip when available in the venv, else uv)
for req in mcp-servers/postgres-mcp/requirements.txt mcp-servers/github-mcp/requirements.txt; do
  .vevn/bin/python -m pip install -q -r "$req" 2>/dev/null \
    || uv pip install --python .vevn/bin/python -q -r "$req"
done

echo "[postgres-mcp] starting on :8001"
.vevn/bin/python mcp-servers/postgres-mcp/server.py &
PG_PID=$!

echo "[github-mcp] starting on :8002"
GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:?set in .env}" \
  .vevn/bin/python mcp-servers/github-mcp/server.py &
GH_PID=$!

echo "[sf-registry] starting on :9010 (Settings tab backend)"
TRUEFORGE_URL="${TRUEFORGE_URL:-http://localhost:8790}" \
  .vevn/bin/python -m schemaforge_core.registry_server &
REG_PID=$!

wait