# Cloudflare deploy (PR #22)

Unified Worker + Containers topology. Cloudflare Containers are Workers-only
(verified against wrangler 4.64.0 schema): the Worker serves the SPA from
`../ui/dist` via `[assets]` and routes `/api/*` to the TrueForge container.

## Prerequisites

- Workers Paid plan (containers is not on free tier)
- `wrangler login` (interactive browser auth)
- Neon project `gentle-cherry-41625953` (dbs `trueforge` + `bookstore`, seeded)
- External managed Redis (Upstash/Redis Cloud) — containers cannot reach a
  Redis container (outbound intercepts HTTP only)

## One-time setup

```bash
cd deploy
npm install
wrangler secret put POSTGRES_PASSWORD     # Neon role password
wrangler secret put POSTGRES_HOST         # e.g. ep-morning-boat-avux3sar-pooler.c-11.us-east-1.aws.neon.tech
wrangler secret put POSTGRES_USER         # neondb_owner
wrangler secret put POSTGRES_PORT         # 5432
wrangler secret put POSTGRES_DB           # trueforge
wrangler secret put REDIS_URL             # redis://...:6379 (Upstash)
wrangler secret put PUBLIC_BASE_URL       # https://schemaforge-worker.<subdomain>.workers.dev
wrangler secret put DAYTONA_API_KEY
wrangler secret put GITHUB_PERSONAL_ACCESS_TOKEN
wrangler secret put CLOUDFLARE_AUTH_TOKEN
wrangler secret put CLOUDFLARE_ACCOUNT_ID
```

Then, with the built UI:

```bash
cd ../ui && npm run build && cd ../deploy
wrangler deploy
```

## Re-registration after deploy

The harness metadata DB is on Neon, but agent/skill/model-provider
registrations are applied via the API and do not survive a container restart:

```bash
set -a && . ../.env && set +a
export TRUEFORGE_URL="https://schemaforge-worker.<subdomain>.workers.dev"
../.vevn/bin/python ../scripts/import_skill.py
../.vevn/bin/python ../scripts/apply_agent.py
```

## Notes

- Keep-warm: `onActivityExpired()` is overridden to not stop; a 5-min cron
  ping doubles it.
- The UI's chat iframe must point at the deployed origin: build the UI with
  `VITE_CHAT_URL=<deployed origin>` (same-origin in production).
- MCP servers are reached from the TrueForge container via `outboundByHost`
  virtual hosts `postgres-mcp.internal` / `github-mcp.internal` (HTTP only).