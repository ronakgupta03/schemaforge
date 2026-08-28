# Cloudflare deploy (PR #22)

Unified Worker + Containers topology with config-first architecture.
Cloudflare Containers are Workers-only (verified against wrangler 4.64.0 schema):
the Worker serves the Evidence UI SPA from `../ui/dist` via `[assets]`, routes
`/api/*` and `/tf/*` to the TrueForge container, and routes `/api/sf/*` to the
SchemaForge registry and MCP container config endpoints.

## Config-First Architecture

Containers boot unconfigured without hardcoded credentials. Operators and judges
configure integrations (Model Providers, Connectors, Services, Sandbox) in the
deployed Evidence UI's **Settings** tab. When Settings are saved and applied, the
registry dynamically derives and upserts the agent manifest.

## Routing (Worker)

- `/api/sf/config/postgres-mcp` → PostgresMcpContainer config port (9001)
- `/api/sf/config/github-mcp`   → GithubMcpContainer config port (9002)
- `/api/sf/*`                   → RegistryContainer (9010) — snapshot, apply-agent, health, config
- `/tf/`                        → TrueForge container root (the embedded chat UI)
- `/assets/*`, `/monacoeditorwork/*` → TrueForge container (chat UI assets)
- `/api/*`                      → TrueForge container (TrueForge API + SSE)
- everything else               → SPA assets (the Evidence UI)

## Prerequisites

- Workers Paid plan (containers is not on free tier)
- `wrangler login` (interactive browser auth)
- Neon project `gentle-cherry-41625953` (dbs `trueforge` + `bookstore`, seeded); set `NEON_CONNECTION_URL` (required env, never commit)
- External managed Redis (Upstash/Redis Cloud) — containers cannot reach a
  Redis container (outbound intercepts HTTP only); set `REDIS_URL`

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
wrangler secret put SF_MCP_CONFIG_TOKEN   # openssl rand -hex 24 (MCP config endpoint auth)
wrangler secret put DAYTONA_API_KEY
wrangler secret put CLOUDFLARE_AUTH_TOKEN
wrangler secret put CLOUDFLARE_ACCOUNT_ID
```

Or run the one-shot script from the repo root (derives Neon creds from
`NEON_CONNECTION_URL`, requires `REDIS_URL` and `GITHUB_REPO_URL` in `.env` or exported, generates `SF_MCP_CONFIG_TOKEN` if unset, checks login):

```bash
NEON_CONNECTION_URL=postgresql://... REDIS_URL=rediss://... scripts/apply-cf-secrets.sh
```

Then, with the built UI:

```bash
cd ../ui && npm run build && cd ../deploy
wrangler deploy
```

## Container Topology & Outbound Interception

- **TrueForgeContainer** (`standard-1`, port 8790): TrueForge server + chat UI.
  Reaches MCP servers via `outboundByHost` virtual hosts
  `http://postgres-mcp.internal/mcp` and `http://github-mcp.internal/mcp`.
- **PostgresMcpContainer** (`lite`, FastMCP port 80, config port 9001):
  Production Postgres MCP server. FastMCP listens on port 80; config endpoint
  listens on port 9001 guarded by `SF_MCP_CONFIG_TOKEN`.
- **GithubMcpContainer** (`lite`, FastMCP port 80, config port 9002):
  GitHub MCP server. FastMCP listens on port 80; config endpoint
  listens on port 9002 guarded by `SF_MCP_CONFIG_TOKEN`.
- **RegistryContainer** (`lite`, port 9010):
  SchemaForge registry server (`sf-registry`). Reaches TrueForge via `outboundByHost`
  `http://trueforge.internal`.

## Post-deploy bootstrap

From the repo root, with `.env` sourced (requires `GITHUB_REPO_URL`, e.g. `https://github.com/ronakgupta03/schemaforge`, required by `import_skill.py`):

```bash
set -a && . ./.env && set +a
export TRUEFORGE_URL="https://schemaforge-worker.<subdomain>.workers.dev"
.vevn/bin/python scripts/register_deployed.py
```

This imports the git skill and invokes the registry's `POST /api/sf/apply-agent`
to initialize the agent registration. Operators then configure models, connectors,
and credentials directly in the **Settings** tab.

## Notes

- Keep-warm: `onActivityExpired()` is overridden to not stop; a 5-min cron
  ping doubles it.
- The UI's chat iframe defaults to the same-origin `/tf/` route in production
  (override with `VITE_CHAT_URL` at build time if needed).
