# @schemaforge/schemaforge

Config-first autonomous database migration agent — TrueForge harness + MCP servers + registry + Evidence UI.

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
6. Evidence UI + API reverse proxy on port 5173 (automatically opened in your default browser).

### Configuration via the Settings Tab

Once the UI opens at `http://localhost:5173`, navigate to the **Settings** tab to configure your environment:

1. **Models**: Configure LLM provider API keys (OpenAI, Anthropic, Gemini, Cloudflare) and choose the active model for SchemaForge.
2. **MCP Servers**: Inspect discovered MCP servers and toggle which servers are attached to the agent.
3. **Connectors**: Set up the production PostgreSQL connection (database DSN / URL) and the GitHub connector with your personal access token and target repository.
4. **Sandbox**: Enable or disable the Daytona sandbox environment used for isolated migration execution and parity verification.
5. **Apply Agent**: Re-generate the agent manifest and apply it to TrueForge. Unconfigured services are simply omitted: without a Postgres connector, the agent skips prod introspection and apply; without a GitHub connector, it saves `out/diff.patch` locally instead of opening a PR.

## Prerequisites

- **Node.js**: v20 or later (`node >= 20`)
- **Python**: Python 3.10+ (`python3` available in `$PATH`)

## CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--port <number>` | `5173` | Port for the Evidence UI web server and proxy |
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
                                      +------------------------------------+
                                      |     Evidence UI (Vite / React)     |
                                      |       http://localhost:5173        |
                                      +-----------------+------------------+
                                                        |
                                                        v
                                      +-----------------+------------------+
                                      |      Reverse Proxy Server          |
                                      |       (schemaforge CLI)            |
                                      +---+-----------+----------+-----+---+
                                          |           |          |     |
             /api/sf/config/postgres-mcp  |           |          |     | /api
                        +-----------------+           |          |     +-----------------+
                        |   /api/sf/config/github-mcp |          |                       |
                        |              +--------------+          | /api/sf               |
                        v              v                         v                       v
               +----------------+ +----------------+ +----------------+ +----------------+
               |  postgres-mcp  | |   github-mcp   | |  sf-registry   | |   TrueForge    |
               |   port 9001    | |   port 9002    | |   port 9010    | |   port 8790    |
               +----------------+ +----------------+ +----------------+ +----------------+
```

- **/api/sf/config/postgres-mcp** -> Proxies to `postgres-mcp` on `127.0.0.1:9001`
- **/api/sf/config/github-mcp** -> Proxies to `github-mcp` on `127.0.0.1:9002`
- **/api/sf** -> Proxies to `sf-registry` on `127.0.0.1:9010`
- **/api** -> Proxies to `TrueForge` on `[::1]:8790` (or `127.0.0.1:8790` if reused)
- **/** -> Serves static Evidence UI SPA with client-side routing fallback

## License

Apache-2.0
