#!/usr/bin/env bash
# Deploy SchemaForge to Cloudflare Containers (PR #22).
# Run from the repo root:  scripts/apply-cf-secrets.sh
# Prerequisites:
#   - `cd deploy && npx wrangler login` done (interactive browser auth)
#   - REDIS_URL exported (external managed Redis: Upstash / Redis Cloud —
#     containers cannot reach a Redis container; outbound intercepts HTTP only)
#   - .env present with CLOUDFLARE_AUTH_TOKEN,
#     CLOUDFLARE_ACCOUNT_ID, GITHUB_REPO_URL (optional: SF_MCP_CONFIG_TOKEN, CF_ACCESS_TEAM, CF_ACCESS_AUD)
#   - NEON_CONNECTION_URL set (owner connection URL; see .env.example). POSTGRES_DB is 'trueforge'.

set -euo pipefail
cd "$(dirname "$0")/.."

if [ -f .env ]; then
  set -a && . ./.env && set +a
fi

: "${NEON_CONNECTION_URL:?set NEON_CONNECTION_URL (Neon owner URL for the project) — see .env.example; never commit it}"
: "${REDIS_URL:?set REDIS_URL to your external managed Redis (Upstash/Redis Cloud)}"
: "${GITHUB_REPO_URL:?set GITHUB_REPO_URL in .env}"

read -r pg_user pg_pass pg_host pg_port <<EOF
$(printf '%s' "$NEON_CONNECTION_URL" | .vevn/bin/python -c '
import sys, urllib.parse
u = urllib.parse.urlsplit(sys.stdin.read().strip())
user = u.username or "neondb_owner"
pw = u.password or ""
host = u.hostname or ""
port = u.port or 5432
print(f"{user} {pw} {host} {port}")
')
EOF

cd deploy

# 1. Auth check
npx wrangler whoami >/dev/null 2>&1 || { echo "Not logged in. Run: npx wrangler login"; exit 1; }

# 2. KV namespace for config replay (idempotent)
TOML_PATH="wrangler.toml"
[ -f "$TOML_PATH" ] || TOML_PATH="deploy/wrangler.toml"
KV_ID=$(grep -oP 'id = "\K[^"]+' "$TOML_PATH" | head -1 || true)
if [ -z "$KV_ID" ] || [ "$KV_ID" = "KV_NAMESPACE_ID_PLACEHOLDER" ]; then
  echo "== creating KV namespace SF_CONFIG_KV"
  KV_OUT=$(npx wrangler kv namespace create SF_CONFIG_KV 2>/dev/null)
  KV_ID=$(printf '%s' "$KV_OUT" | grep -oP '(?:id = "|id":\s*")\K[^"]+' | head -1 || true)
  if [ -z "$KV_ID" ] || [ "$KV_ID" = "KV_NAMESPACE_ID_PLACEHOLDER" ]; then
    echo "ERROR: failed to create SF_CONFIG_KV namespace" >&2
    exit 1
  fi
  echo "== injected KV namespace id: $KV_ID"
  sed -i "s/KV_NAMESPACE_ID_PLACEHOLDER/$KV_ID/" "$TOML_PATH"
fi

secret() {
  local name="$1" value="$2"
  echo "== secret: $name"
  printf '%s\n' "$value" | npx wrangler secret put "$name" --name schemaforge-worker
}

# 3. All secrets except PUBLIC_BASE_URL (deploy URL is unknown until first deploy)
secret POSTGRES_USER "$pg_user"
secret POSTGRES_PASSWORD "$pg_pass"
secret POSTGRES_HOST "$pg_host"
secret POSTGRES_PORT "$pg_port"
secret POSTGRES_DB "trueforge"
secret REDIS_URL "$REDIS_URL"
sf_mcp_config_token="${SF_MCP_CONFIG_TOKEN:-$(openssl rand -hex 24)}"
secret SF_MCP_CONFIG_TOKEN "$sf_mcp_config_token"
secret CLOUDFLARE_AUTH_TOKEN "${CLOUDFLARE_AUTH_TOKEN:?set CLOUDFLARE_AUTH_TOKEN in .env}"
secret CLOUDFLARE_ACCOUNT_ID "${CLOUDFLARE_ACCOUNT_ID:?set CLOUDFLARE_ACCOUNT_ID in .env}"

if [ -n "${CF_ACCESS_TEAM:-}" ]; then
  secret CF_ACCESS_TEAM "$CF_ACCESS_TEAM"
else
  echo "== skipping CF_ACCESS_TEAM (unset in .env)"
fi

if [ -n "${CF_ACCESS_AUD:-}" ]; then
  secret CF_ACCESS_AUD "$CF_ACCESS_AUD"
else
  echo "== skipping CF_ACCESS_AUD (unset in .env)"
fi
# 4. First deploy (captures the workers.dev URL)
echo "== deploy (1st)"
deploy_out=$(npx wrangler deploy 2>&1) || true
echo "$deploy_out" | tail -15
url=$(printf '%s\n' "$deploy_out" | grep -oE 'https://schemaforge-worker\.[a-z0-9-]+\.workers\.dev' | head -1) || true
if [ -z "$url" ]; then
  echo "!! Could not detect deploy URL; set PUBLIC_BASE_URL manually:" >&2
  echo "   printf '%s\\n' '<URL>' | npx wrangler secret put PUBLIC_BASE_URL --name schemaforge-worker" >&2
  echo "   then: npx wrangler deploy" >&2
  exit 1
fi

# 5. PUBLIC_BASE_URL + redeploy so the container boots with it
echo "== detected URL: $url"
secret PUBLIC_BASE_URL "$url"
echo "== redeploy with PUBLIC_BASE_URL"
npx wrangler deploy 2>&1 | tail -8

echo
echo "Deployed: $url"
echo "Next: re-register agent+skill against the deployed URL, then run the smoke test."
