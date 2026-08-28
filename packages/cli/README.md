# @schemaforge/schemaforge

Config-first autonomous database migration agent — TrueForge harness + MCP servers + registry + Evidence UI.

## Quickstart

Run with one command:

```bash
npx @schemaforge/schemaforge
```

This starts:
1. Python virtual environment bootstrap (first-run only, installed at `~/.schemaforge/.sfenv`)
2. `postgres-mcp` (config port 9001, transport port 8001)
3. `github-mcp` (config port 9002, transport port 8002)
4. `sf-registry` (port 9010)
5. `TrueForge` agent harness (`npx @truefoundry/trueforge` on port 8790)
6. Evidence UI + API reverse proxy on port 5173 (automatically opened in your default browser)

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

| Variable | Default | Description |
|----------|---------|-------------|
| `SF_PYTHON` | `python3` | Custom Python binary path for venv creation |
| `SF_STATE_DIR` | `~/.schemaforge` | Base directory for state files and venv |
| `TRUEFORGE_PORT` | `8790` | Port for TrueForge backend |
| `TRUEFORGE_HOST` | `127.0.0.1` | Host for TrueForge backend |

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
- **/api** -> Proxies to `TrueForge` on `[::1]:8790`
- **/** -> Serves static Evidence UI SPA with client-side routing fallback

## License

Apache-2.0
