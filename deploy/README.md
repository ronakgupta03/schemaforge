# Cloudflare deploy (PR #22)

Unified Worker + Containers topology. Cloudflare Containers are Workers-only
(verified against wrangler 4.64.0 schema): the Worker serves the SPA from
`../ui/dist` via `[assets]` and routes to the TrueForge container.

## Routing (Worker)

- `/tf/`            → TrueForge container root (the embedded chat UI)
- `/assets/*`, `/monacoeditorwork/*` → TrueForge container (its UI assets are
  absolute; the SPA's own bundles are built under `/static/*` to avoid collision)
- `/api/*`          → TrueForge container (API + SSE)
- everything else   → SPA assets (the Evidence UI)

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

Or run the one-shot script from the repo root (derives Neon creds from the
owner URL, requires `REDIS_URL` exported, checks login):

```bash
REDIS_URL=rediss://... scripts/apply-cf-secrets.sh
```

Then, with the built UI:

```bash
cd ../ui && npm run build && cd ../deploy
wrangler deploy
```

The MCP containers listen on port 80 (outbound interception is HTTP(S)
80/443 only) and are reached by the TrueForge container at
`http://postgres-mcp.internal/mcp` / `http://github-mcp.internal/mcp`.

## Post-deploy registration

The harness metadata DB is on Neon, but settings manifests (MCP servers,
model provider) are created via the API and do not survive a fresh container
boot. From the repo root, with `.env` sourced:

```bash
set -a && . ./.env && set +a
export TRUEFORGE_URL="https://schemaforge-worker.<subdomain>.workers.dev"
.vevn/bin/python scripts/register_deployed.py
```

This registers postgres-prod + github MCP settings (internal URLs), the
cloudflare model provider, the git skill, and the schemaforge agent.

## Notes

- Keep-warm: `onActivityExpired()` is overridden to not stop; a 5-min cron
  ping doubles it.
- The UI's chat iframe defaults to the same-origin `/tf/` route in production
  (override with `VITE_CHAT_URL` at build time if needed).
- MCP servers are reached from the TrueForge container via `outboundByHost`
  virtual hosts `postgres-mcp.internal` / `github-mcp.internal` (HTTP only).