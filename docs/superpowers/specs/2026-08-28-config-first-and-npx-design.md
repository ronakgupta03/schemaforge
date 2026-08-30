# SchemaForge Config-First + npx Package — Design

> Date: 2026-08-28
> Status: Approved by user (2026-08-28; three forks decided: `@schemaforge/schemaforge`, runtime `/config` endpoints, feature-first sequencing)

## 1. Problem

SchemaForge currently hardcodes its runtime wiring:

- `scripts/apply_agent.py` hardcodes the model FQN (`SCHEMAFORGE_MODEL` env with a
  `local/qwen3.8-27b` fallback), the `mcp_servers` list (postgres-prod + github),
  the skill, and the sandbox config.
- `agent/instructions.md` hardcodes the repo URL (`ronakgupta03/schemaforge`),
  the tool inventory, and the PR step.
- `mcp-servers/postgres-mcp/server.py` and `mcp-servers/github-mcp/server.py`
  read `os.environ["DATABASE_URL"]` / `os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"]`
  at import — **crash if unset**.
- `deploy/` (Worker routing, container envVars, secrets) assumes a fixed
  three-container topology with hardcoded credentials at deploy time.

The user wants: every integration (MCP servers, model provider/model, sandbox)
**configurable via the UI**, nothing hardcoded, graceful degradation when a
service is not configured, identical configuration surface locally and on the
hosted/deployed instance, and the whole project shipped as **one npx package**
(`@schemaforge/schemaforge`) bundling the UI, both MCP servers, and the
TrueForge server. Judges must be able to configure everything on the deployed
instance without touching code or secrets.

## 2. Goals / Non-goals

**Goals**
- Any MCP server (postgres, github, or a user's own) is creatable, editable,
  enable/disable-able, and deletable from the UI.
- The agent manifest is derived from live settings — missing services are
  simply omitted, never crashed on.
- `postgres-mcp` and `github-mcp` boot with no credentials and expose a
  token-guarded `POST /config` endpoint for live configuration (no restart).
- `npx @schemaforge/schemaforge` boots the full stack locally: TrueForge
  server + postgres-mcp + github-mcp + UI (built dist, proxied) +
  auto-registration, then opens the browser.
- The Cloudflare deploy (after this feature) boots containers unconfigured;
  judges configure live in the deployed UI.

**Non-goals**
- No multi-tenancy/teams; no per-user config isolation (hosted mode agent
  library is already shared).
- No migration-engine rewrite; Alembic + `schemaforge_core` stay as-is.
- No UI for sandbox *provisioning internals* beyond the Daytona API key.

## 3. Architecture

### 3.1 MCP servers: lazy config + `POST /config`

Both MCP servers change from import-time env reads to a `Config` holder:

- `postgres-mcp`: `Config.database_url` (None until set). `_conn()` raises a
  clear `RuntimeError("postgres-prod is not configured: set a DATABASE_URL via the Settings panel or POST /config")` when None. All read/write tools
  surface that error as a tool result (MCP tool error), never a server crash.
- `github-mcp`: `Config.token` + `Config.default_repo` (None until set).
  `get_repo`/`branch_exists`/`create_branch`/`write_file`/`open_pull_request`
  default `repo` to `default_repo` when the arg is empty; `_client()` raises the
  same clear "not configured" error when token is None.

Both expose:

```
POST /config
Authorization: Bearer <SF_MCP_CONFIG_TOKEN>   (env; unset -> 503 "config disabled")
Content-Type: application/json

postgres-mcp:  { "database_url": "postgresql://..." }
github-mcp:    { "token": "ghp_...", "default_repo": "owner/repo" }

202 -> { "ok": true }
400 -> { "error": "<message>" }
```

- Config persists to a local file (`<state-dir>/postgres-mcp.json` /
  `<state-dir>/github-mcp.json`, state-dir default `~/.schemaforge`, override
  `SF_STATE_DIR`) and is re-loaded on boot. Live updates apply immediately.
- Implemented as a plain `http.server` on a second port (`SF_CONFIG_PORT`,
  default 9001/9002) — the FastMCP streamable-HTTP transport stays untouched.
- In the Cloudflare deploy, the Worker routes `/api/sf/config/postgres-mcp` and
  `/api/sf/config/github-mcp` to these ports; locally the vite proxy does the
  same. `SF_MCP_CONFIG_TOKEN` is a shared secret (env locally, Worker secret in
  deploy).

### 3.2 UI Settings panel

A new `Settings` tab in the Evidence UI (same panel surface in local dev and
deploy; same-origin `/api/*` + `/api/sf/*` in both).

Sections:

1. **Models**
   - List configured model providers + their models (GET `/api/v1/settings/model-providers`, `/api/v1/models`).
   - Add a custom provider: name, base_url, api_key, model_id(s) + names
     (PUT `/api/v1/settings/model-providers` — collection upsert keyed by
     manifest name; verified shape `{"manifest": {...}}`).
   - Delete provider.
   - Select the agent's model (dropdown of `GET /api/v1/models` FQNs) →
     stored as the manifest `model.name` on Apply.

2. **Connectors (MCP servers)**
   - List TrueForge MCP server settings (GET `/api/v1/settings/mcp-servers`).
   - Add/edit: name (ResourceName regex `^[a-z](?:[a-z0-9._-]{0,62}[a-z0-9])$`,
     max 64), url, description, auth (none | header | dcr; header values are
     secret: blank keeps stored value, non-blank rotates) —
     PUT `/api/v1/settings/mcp-servers` `{"manifest": {...}}`.
   - Toggle "attached to agent" (enable/disable) + approval policy override
     (default by name: postgres-prod → `@write,@destructive`; others → `[]`).
   - Delete server (DELETE `/api/v1/settings/mcp-servers/{name}`).

3. **Services (SchemaForge-owned MCP servers)**
   - postgres: DATABASE_URL field → `POST /api/sf/config/postgres-mcp`.
   - github: token + default repo fields → `POST /api/sf/config/github-mcp`.
   - Status badges: configured / not configured (probe `GET /config` state or
     the last known config write result).

4. **Sandbox**
   - Daytona API key (PUT `/api/v1/settings/sandbox-providers` —
     `{"manifest": {"type": "daytona", "auth": {"api_key": ...}, "exec_timeout_ms": ...,
     "auto_stop/auto_archive/auto_delete": ...}}`).
   - Shows capabilities state (sandbox.enabled / skill.enabled) from
     GET `/api/v1/capabilities`.

5. **Apply agent**
   - Button "Save & apply agent" → runs the manifest builder (3.3) against
     live settings → POST/PUT `/api/v1/agents` (find by name → PUT by id).
   - Shows the resulting manifest summary + any omitted services.

### 3.3 Derived agent manifest

`scripts/apply_agent.py` is refactored into a **manifest builder**:

```
build_manifest(settings: SettingsSnapshot, instructions: str) -> AgentSpec
```

- `model`: from the UI-selected FQN (persisted in `~/.schemaforge/agent.json`,
  env `SCHEMAFORGE_MODEL` fallback), defaulting to the first model of the
  first configured provider if neither set.
- `mcp_servers`: exactly the enabled servers from settings; per-server
  `require_approval_for_tools` from the policy map (postgres-prod →
  `["@write","@destructive"]`, github → `[]`, user servers → `[]` unless the
  UI override says otherwise), `preload` default false (postgres-prod true).
- `skills`: `["schemaforge-migration"]` only when `capabilities.sandbox.enabled`.
- `config.sandbox.enabled`: only when a sandbox provider is configured.
- `config` (iteration_limit 100, dynamic_sub_agents/generative_ui/
  ask_user_questions/context_management/large_tool_response true) — fixed
  defaults, no longer env-dependent.

**Decision: the registry is its own small module.** `schemaforge_registry` (in
`core`, HTTP on `SF_REGISTRY_PORT` default 9010) owns `build_manifest` + the
agents upsert + mcp-server settings helpers. postgres-mcp and github-mcp stay
pure MCP servers with `/config`. The UI calls `POST /api/sf/apply-agent`
(registry), never touching MCP servers directly for Apply; the existing
`apply_agent.py` CLI becomes a thin wrapper over the same builder — one source
of truth for the policy. Apply requires the registry service up (documented in
the UI as "registry offline" otherwise).

### 3.4 npx package `@schemaforge/schemaforge`

`npm pack` of a CLI:

- `bin`: `schemaforge` → Node CLI (no build step; `bin/schemaforge.js`).
- Bundled assets: `ui/dist/` (built SPA), `mcp-servers/{postgres-mcp,github-mcp}/`
  (Python sources), `core/` (wheel or source), `agent/instructions.md`,
  `skills/schemaforge-migration/`, `scripts/` (sandbox_setup.sh, seed_prod.sh).
- Runtime behavior of `npx @schemaforge/schemaforge` (local mode):
  1. Create/verify Python venv (`.sfenv` in state dir) + install
     `core` + `mcp` requirements (first run only).
  2. Start postgres-mcp (SF_CONFIG_PORT 9001, MCP port 8001).
  3. Start github-mcp (SF_CONFIG_PORT 9002, MCP port 8002).
  4. Start registry (SF_REGISTRY_PORT 9010).
  5. Start TrueForge server (standalone, SQLite at state dir, port 8790) —
     depends on `@truefoundry/trueforge`.
  6. Serve `ui/dist` on port 5173 with vite-style proxy:
     `/api/*` → `http://[::1]:8790`, `/api/sf/*` → registry, plus
     `/api/sf/config/postgres-mcp` → 9001, `/api/sf/config/github-mcp` → 9002.
  7. Bootstrap once: register skill (git skill from `GITHUB_REPO_URL` env or
     the packaged skill dir), register agent via the registry builder.
  8. Open browser at `http://localhost:5173`.
- Flags: `--no-open`, `--port`, `--state-dir`, `--hosted` (documented; hosted
  mode expects POSTGRES_*/REDIS_URL env and skips step 1-4 python bootstrapping
  — actually hosted keeps local MCP servers + registry; only TrueForge switches
  to hosted mode).

Dependency policy: `@truefoundry/trueforge` (server), no other runtime deps;
Python deps (`mcp>=1.9,<2`, `psycopg[binary]`, `httpx`, `schemaforge_core`)
installed into the venv.

## 4. Data flow

```
UI Settings tab
  ├─ Models     → PUT /api/v1/settings/model-providers
  ├─ Connectors → PUT|DELETE /api/v1/settings/mcp-servers
  ├─ Services   → POST /api/sf/config/postgres-mcp|github-mcp  (Worker/vite proxy → MCP /config)
  ├─ Sandbox    → PUT /api/v1/settings/sandbox-providers
  └─ Apply      → POST /api/sf/apply-agent  (registry → build_manifest + agents upsert)
```

Local: UI (5173) → vite proxy → [TrueForge 8790 | registry 9010 | MCP config 9001/9002].
Deploy: UI (Worker) → Worker routes → [TrueForge container | registry container | MCP config ports].

## 5. Error handling

- Unconfigured MCP server: tools return explicit "not configured" errors; the
  agent (instructions updated) treats missing servers as "skip that step and
  note it", never as fatal.
- Invalid config writes: 400 with a specific message (DSN parse check, token
  empty, ResourceName violation surfaced from TrueForge's 400 body).
- `POST /config` without the token: 401; token env unset: 503.
- Apply with no configured model: manifest uses default or 422 with
  "no model provider configured".
- Apply with registry down: UI badge "registry offline".

## 6. Testing

- `core` registry: unit tests for `build_manifest` (model selection, mcp_servers
  inclusion/exclusion, approval policy by name, skill gating on sandbox,
  iteration_limit/other config defaults) — pure function, no HTTP.
- `postgres-mcp`/`github-mcp`: `/config` endpoint tests (set → tools work;
  unset → clear error; bad token → 401; persistence file round-trip) via
  `TestClient`/httpx against a live server on ephemeral ports.
- UI: component tests for Settings tab (form state, provider/server
  add/edit/delete flows, apply button wiring) with mocked sfApi + registry
  client; existing 24-test suite stays green.
- npx package: smoke — `npm pack`, install into a temp dir, run
  `npx schemaforge --no-open` against an ephemeral state dir, assert TrueForge
  `/api/v1/capabilities` 200, registry `/health` 200, both MCP `/config` reachable,
  agent registered with correct manifest.
- Deploy (after): same smoke against the deployed Worker origin.

## 7. Sequencing

1. **PR #23 — config-first MCP servers + registry** (core registry module,
   postgres-mcp/github-mcp `/config`, tests).
2. **PR #24 — instructions + agent derivation** (conditional instructions,
   `apply_agent.py` → builder wrapper).
3. **PR #25 — UI Settings tab** (Models/Connectors/Services/Sandbox/Apply).
4. **PR #26 — npx package** (CLI orchestrator, bundled assets, smoke test).
5. **Rework PR #22** — Cloudflare deploy: containers boot unconfigured,
   Worker routes `/api/sf/*`, secrets shrink, deployed smoke.

Each PR Qodo-reviewed and merged before the next starts (established gate).

## 8. Open risks

- `@schemaforge/schemaforge` npm publish needs an npm account/token (user
  action; package is `npm pack`-able + installable from git as fallback).
- Hosted-mode TrueForge (Postgres+Redis) remains the untested deploy risk;
  the npx package's local default (standalone) is the judge path.
- Registry coupling: Apply requires the registry service up (documented in UI).