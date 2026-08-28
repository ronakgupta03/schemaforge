#!/usr/bin/env bash
# Deploy SchemaForge to Cloudflare Containers (PR #22).
# Run from the repo root:  scripts/apply-cf-secrets.sh
# Prerequisites:
#   - `cd deploy && npx wrangler login` done (interactive browser auth)
#   - REDIS_URL exported (external managed Redis: Upstash / Redis Cloud —
#     containers cannot reach a Redis container; outbound intercepts HTTP only)
#   - .env present with DAYTONA_API_KEY, CLOUDFLARE_AUTH_TOKEN,
#     CLOUDFLARE_ACCOUNT_ID (optional: SF_MCP_CONFIG_TOKEN; generated if unset)
# Neon owner URL is read from NEON_CONNECTION_URL if set, else the hardcoded
# project URL (gentle-cherry-41625953). POSTGRES_DB is 'trueforge'.

set -euo pipefail
cd "$(dirname "$0")/.."

: "${NEON_CONNECTION_URL:=postgresql://neondb_owner:npg_7dYZ1lRPfXxQ@ep-morning-boat-avux3sar-pooler.c-11.us-east-1.aws.neon.tech/neondb?channel_binding=require&sslmode=require}"
: "${REDIS_URL:?set REDIS_URL to your external managed Redis (Upstash/Redis Cloud)}"

pg_user=$(printf '%s' "$NEON_CONNECTION_URL" | sed -E 's|postgresql://([^:]+):.*|\1|')
pg_pass=$(printf '%s' "$NEON_CONNECTION_URL" | sed -E 's|postgresql://[^:]+:([^@]+)@.*|\1|')
pg_host=$(printf '%s' "$NEON_CONNECTION_URL" | sed -E 's|postgresql://[^@]+@([^/:]+).*|\1|')
pg_port=$(printf '%s' "$NEON_CONNECTION_URL" | sed -E 's|postgresql://[^@]+@[^/:]+:([0-9]+).*|\1|')
pg_port=${pg_port:-5432}

if [ -f .env ]; then
  set -a && . ./.env && set +a
fi

cd deploy

# 1. Auth check
npx wrangler whoami >/dev/null 2>&1 || { echo "Not logged in. Run: npx wrangler login"; exit 1; }

secret() {
  local name="$1" value="$2"
  echo "== secret: $name"
  printf '%s\n' "$value" | npx wrangler secret put "$name" --name schemaforge-worker
}

# 2. All secrets except PUBLIC_BASE_URL (deploy URL is unknown until first deploy)
secret POSTGRES_USER "$pg_user"
secret POSTGRES_PASSWORD "$pg_pass"
secret POSTGRES_HOST "$pg_host"
secret POSTGRES_PORT "$pg_port"
secret POSTGRES_DB "trueforge"
secret REDIS_URL "$REDIS_URL"
sf_mcp_config_token="${SF_MCP_CONFIG_TOKEN:-$(openssl rand -hex 24)}"
secret SF_MCP_CONFIG_TOKEN "$sf_mcp_config_token"
secret DAYTONA_API_KEY "${DAYTONA_API_KEY:?set DAYTONA_API_KEY in .env}"
secret CLOUDFLARE_AUTH_TOKEN "${CLOUDFLARE_AUTH_TOKEN:?set CLOUDFLARE_AUTH_TOKEN in .env}"
secret CLOUDFLARE_ACCOUNT_ID "${CLOUDFLARE_ACCOUNT_ID:?set CLOUDFLARE_ACCOUNT_ID in .env}"

# 3. First deploy (captures the workers.dev URL)
echo "== deploy (1st)"
deploy_out=$(npx wrangler deploy 2>&1)
echo "$deploy_out" | tail -15
url=$(printf '%s\n' "$deploy_out" | grep -oE 'https://schemaforge-worker\.[a-z0-9-]+\.workers\.dev' | head -1)
if [ -z "$url" ]; then
  echo "!! Could not detect deploy URL; set PUBLIC_BASE_URL manually:" >&2
  echo "   printf '%s\\n' '<URL>' | npx wrangler secret put PUBLIC_BASE_URL --name schemaforge-worker" >&2
  echo "   then: npx wrangler deploy" >&2
  exit 1
fi

# 4. PUBLIC_BASE_URL + redeploy so the container boots with it
echo "== detected URL: $url"
secret PUBLIC_BASE_URL "$url"
echo "== redeploy with PUBLIC_BASE_URL"
npx wrangler deploy 2>&1 | tail -8

echo
echo "Deployed: $url"
echo "Next: re-register agent+skill against the deployed URL, then run the smoke test."
