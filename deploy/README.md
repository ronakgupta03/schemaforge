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


### KV-Backed Config Replay (Container Sleep Survival)

Cloudflare container disk is ephemeral across container sleeps. To ensure operator
configurations survive container wake without manual re-entry:
- Successful `POST` requests to `/api/sf/config/postgres-mcp`, `/api/sf/config/github-mcp`, `/api/sf/config`, and `/api/sf/apply-agent` are automatically persisted by the Worker into the `SF_CONFIG_KV` KV namespace.
- On Worker cold start / container wake, the first `/api/sf/*` request triggers an automatic replay of all saved configurations from `SF_CONFIG_KV` to the respective container endpoints (Postgres MCP on port 9001, GitHub MCP on port 9002 with `SF_MCP_CONFIG_TOKEN`, and Registry on port 9010).
- `scripts/apply-cf-secrets.sh` idempotently creates the `SF_CONFIG_KV` namespace and injects its namespace ID into `deploy/wrangler.toml`.
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

## Cloudflare Access Provisioning

To secure the deployed Worker with Cloudflare Access:
1. **Enable Access on the Zone/Route:** In Cloudflare Zero Trust dashboard, navigate to **Access** > **Applications**.
2. **Create an Application for Worker Hostname:** Add a **Self-Hosted** application pointing to the Worker domain (e.g., `schemaforge-worker.<subdomain>.workers.dev` or your custom domain).
3. **Configure Access Policies:** Define which users or identity providers are allowed to access the application.
4. **Note the AUD Tag:** In the application overview/settings, copy the **Application Audience (AUD)** tag.
5. **Set Worker Secrets:** Set `CF_ACCESS_TEAM` (your Zero Trust team name) and `CF_ACCESS_AUD` (the AUD tag) in `.env`, then run `scripts/apply-cf-secrets.sh` (or set them manually via `wrangler secret put CF_ACCESS_TEAM` and `wrangler secret put CF_ACCESS_AUD`).

## Access Model & Security

### Gate Matrix

The deploy worker enforces a three-state gate matrix for protected routes (`/api/v1/settings/*` and `/api/sf/*`):

| State | Configuration | Gate Enforcement | Target Environment |
| --- | --- | --- | --- |
| **Access-only** | `CF_ACCESS_TEAM` + `CF_ACCESS_AUD` set | `CF-Access-Jwt-Assertion` validated against team JWKS (returns 401 if missing/invalid) | Production deployment with browser UI behind Cloudflare Access |
| **bearer-only API clients** | Access unset, `SF_DEPLOY_TOKEN` set | `Authorization: Bearer <token>` required (returns 401 if missing/invalid) | Headless API clients, CI/CD automation without Cloudflare Access |
| **open + warning** | Neither configured | Open / unrestricted, logs `deploy gate DISABLED (set CF_ACCESS_TEAM + CF_ACCESS_AUD or SF_DEPLOY_TOKEN)` | Local development & testing |

### Key Security Primitives

- **Cloudflare Access (Access-only Gate):** When configured (`CF_ACCESS_TEAM` and `CF_ACCESS_AUD`), the Worker cryptographically verifies the `CF-Access-Jwt-Assertion` header via RS256 against Cloudflare's public team JWKS (`https://<CF_ACCESS_TEAM>.cloudflareaccess.com/cdn-cgi/access/certs`), validating expiration and AUD audience.
- **SF_DEPLOY_TOKEN (bearer-only API clients):** When Cloudflare Access is not configured, the Worker supports `SF_DEPLOY_TOKEN` as a bearer-token layer for external API clients and automation scripts.
- **SPA Tokenless Design:** The Evidence UI SPA carries no deploy token in its client bundle. Browser users authenticate directly through Cloudflare Access at the edge.
- **SF_MCP_CONFIG_TOKEN:** Guards container configuration endpoints (Postgres MCP on port 9001, GitHub MCP on port 9002).
