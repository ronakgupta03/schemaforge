# @schemaforge/schemaforge

Config-first autonomous database migration agent — TrueForge harness + MCP servers + registry.

## Quickstart

Run with one command:

```bash
npx @schemaforge/schemaforge
```

This starts:
1. Python virtual environment bootstrap (first-run only, installed at `~/.schemaforge/.sfenv`).
2. `postgres-mcp` (config port 9001, transport port 8001).
3. `github-mcp` (config port 9002, transport port 8002).
4. `sf-registry` (port 9010).
5. `TrueForge` agent harness (`npx @truefoundry/trueforge` on port 8790).
6. A local mirror on port 5173 (config proxy + redirect), and the TrueForge UI is opened in your default browser.

### The TrueForge UI

Chat with the `schemaforge` agent in the TrueForge UI at
`http://[::1]:8790` (or `http://localhost:8790` when TrueForge reuses an
IPv4 listener). The CLI patches the served frontend automatically on
every launch so impact-graph mermaid blocks render inside chat
(`scripts/patch-trueforge-mermaid.py`, idempotent).

Evidence artifacts (`graph.mmd`, `report.md`, `migration.sql`,
`diff.patch`, `verify.json`) are saved per session in the sandbox and
downloadable from chat. The development workspace's forked TrueForge UI
(`trueforge-ui-fork`) additionally adds evidence tabs —
**Impact / Report / Changes / Verification / Activity** — and a
**SchemaForge** section in Settings; the published package does not bundle
that fork.

### Configuration via the Settings Tab

Open **Settings** in the TrueForge UI to configure your environment (the
stock UI ships four sections; the development-workspace fork adds the
SchemaForge section):

1. **Models**: Configure LLM provider API keys (OpenAI, Anthropic, Gemini, Cloudflare) and choose the active model for SchemaForge.
2. **Connectors**: Inspect discovered MCP servers and toggle which servers are attached to the agent.
3. **Skills**: Manage the `schemaforge-migration` git skill.
4. **Sandbox providers**: Configure the Daytona sandbox used for isolated migration execution and parity verification.
5. **SchemaForge** *(dev-workspace fork only)*: Production PostgreSQL DSN, GitHub personal access token + default repo, config token, and an **Apply Agent** button that re-generates the agent manifest.

Unconfigured services are simply omitted: without a Postgres connector, the
agent skips prod introspection and apply; without a GitHub connector, it
saves `out/diff.patch` locally instead of opening a PR.

## Prerequisites

- **Node.js**: v20 or later (`node >= 20`)
- **Python**: Python 3.10+ (`python3` available in `$PATH`)

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--port <number>` | `5173` | Port for the local mirror web server and proxy |
| `--state-dir <path>` | `~/.schemaforge` | Directory for Python venv, configuration files, and state |
| `--no-open` | `false` | Prevent opening the browser automatically upon launch |

### Environment Variables

All settings can be configured in the UI or pre-seeded via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | _None_ | PostgreSQL connection DSN for `postgres-mcp` (e.g. `postgresql://postgres:postgres@localhost:5432/demo_prod`) |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | _None_ | GitHub personal access token (`ghp_...` or `github_pat_...`) used by `github-mcp` to create migration branches and pull requests |
| `GITHUB_REPO_URL` | _None_ | Target GitHub repository (`owner/repo` or full URL) for branches and pull requests |
| `DAYTONA_API_KEY` | _None_ | API key for Daytona workspace sandbox execution and parity verification |
| `SF_MCP_CONFIG_TOKEN` | _None_ | Optional bearer token guarding `POST /config` endpoints on MCP servers in multi-user deployments |
| `SF_PYTHON` | `python3` | Custom Python binary path for venv creation and MCP server execution |
| `SF_STATE_DIR` | `~/.schemaforge` | Base directory for configuration state, venv, and cached artifacts |
| `TRUEFORGE_PORT` | `8790` | Port for TrueForge agent harness backend |
| `TRUEFORGE_HOST` | `::1` | Host for TrueForge backend (`::1` IPv6 loopback or `127.0.0.1`) |
| `SF_POSTGRES_CONFIG_PORT` | `9001` | Config endpoint port for `postgres-mcp` |
| `SF_GITHUB_CONFIG_PORT` | `9002` | Config endpoint port for `github-mcp` |
| `SF_POSTGRES_PORT` | `8001` | MCP streamable-http transport port for `postgres-mcp` |
| `SF_GITHUB_PORT` | `8002` | MCP streamable-http transport port for `github-mcp` |
| `SF_REGISTRY_PORT` | `9010` | Port for `sf-registry` server |

## Architecture

```
                                   +----------------------------+
                                   |    TrueForge chat UI :8790 |
                                   |  (SchemaForge evidence     |
                                   |   tabs + Settings section) |
                                   +-------------+--------------+
                                                 ^  /tf  /api  (redirect + proxy)
                                   +-------------+--------------+
                                   |    Local mirror :5173      |
                                   |    (schemaforge CLI)       |
                                   +---+-----------+------+-----+
                                       |           |      |
        /api/sf/config/postgres-mcp    |           |      | /api/sf
                   +-------------------+           |      +----------------+
                   |   /api/sf/config/github-mcp   |                     |
                   v              v                v                     v
          +----------------+ +----------------+ +----------------+ +----------------+
          |  postgres-mcp  | |   github-mcp   | |  sf-registry   | |   TrueForge    |
          |   port 9001    | |   port 9002    | |   port 9010    | |   port 8790    |
          +----------------+ +----------------+ +----------------+ +----------------+
```

- **/api/sf/config/postgres-mcp** -> Proxies to `postgres-mcp` on `127.0.0.1:9001`
- **/api/sf/config/github-mcp** -> Proxies to `github-mcp` on `127.0.0.1:9002`
- **/api/sf** -> Proxies to `sf-registry` on `127.0.0.1:9010`
- **/api**, **/tf** -> Proxies to `TrueForge` on `[::1]:8790` (or `127.0.0.1:8790` if reused)
- **/** -> Redirects to the TrueForge UI

## License

Apache-2.0