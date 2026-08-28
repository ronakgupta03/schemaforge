#!/usr/bin/env bash
# Apply Cloudflare worker secrets for the SchemaForge deploy (PR #22).
# Run from the repo root:  scripts/apply-cf-secrets.sh
# Prerequisites:
#   - wrangler logged in (interactive `wrangler login`) or CLOUDFLARE_API_TOKEN
#     with Workers Scripts edit permission for the account
#   - REDIS_URL exported (external managed Redis: Upstash / Redis Cloud —
#     containers cannot reach a Redis container; outbound intercepts HTTP only)
#   - .env present with DAYTONA_API_KEY, GITHUB_PERSONAL_ACCESS_TOKEN,
#     CLOUDFLARE_AUTH_TOKEN, CLOUDFLARE_ACCOUNT_ID
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

secret() {
  local name="$1" value="$2"
  echo "== secret: $name"
  printf '%s\n' "$value" | npx wrangler secret put "$name" --name schemaforge-worker
}

secret POSTGRES_USER "$pg_user"
secret POSTGRES_PASSWORD "$pg_pass"
secret POSTGRES_HOST "$pg_host"
secret POSTGRES_PORT "$pg_port"
secret POSTGRES_DB "trueforge"
secret REDIS_URL "$REDIS_URL"
secret PUBLIC_BASE_URL "https://schemaforge-worker.${CLOUDFLARE_ACCOUNT_ID:-workers-dev}.workers.dev"
secret DAYTONA_API_KEY "${DAYTONA_API_KEY:?set DAYTONA_API_KEY in .env}"
secret GITHUB_PERSONAL_ACCESS_TOKEN "${GITHUB_PERSONAL_ACCESS_TOKEN:?set GITHUB_PERSONAL_ACCESS_TOKEN in .env}"
secret CLOUDFLARE_AUTH_TOKEN "${CLOUDFLARE_AUTH_TOKEN:?set CLOUDFLARE_AUTH_TOKEN in .env}"
secret CLOUDFLARE_ACCOUNT_ID "${CLOUDFLARE_ACCOUNT_ID:?set CLOUDFLARE_ACCOUNT_ID in .env}"

echo "All secrets applied. Next: cd deploy && npx wrangler deploy"