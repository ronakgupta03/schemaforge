# SchemaForge — Hackathon Implementation Plan

**Date:** 2026-08-26 (Day 3 of 7; deadline **Aug 30, 20:00 London time**)
**Hackathon:** The Agent Harness Hackathon (WeMakeDevs × TrueFoundry × Qodo), mission TF-007
**Repo:** `/home/utsav/Github/schemaforge` (git branch `Utsav`, not yet pushed)

---

## Goal

Build **SchemaForge**: an autonomous, AST-aware, zero-downtime database migration &
refactoring agent on TrueForge. The agent takes a plain-English schema change request,
deterministically analyzes the live Postgres schema + the Python application code,
builds an impact graph, authors a data-preserving Alembic migration and the matching
application refactors, proves safety in the TrueForge Daytona sandbox (tests + data
parity + EXPLAIN ANALYZE), emits a safety report, and **pauses for human approval
before executing DDL against the production database** — after which it opens a
GitHub pull request with the migration + code changes.

Every substantive change lands on `main` through a GitHub PR reviewed by **Qodo**
(direct pushes to main do not count as reviewed work).

## Architecture

```
User intent ("split users into users + user_profiles")
        │
        ▼
┌────────────────────────── TrueForge (localhost:8790) ─────────────────────────┐
│  Root agent: local/qwen3.8-27b (llama.cpp @ localhost:8000/v1, custom)        │
│  ├── skill: schemaforge-migration (git-imported, loaded in sandbox)           │
│  ├── MCP postgres-prod  (http://localhost:8001/mcp, our FastMCP server)       │
│  │     read-only tools + execute_ddl [annotated destructive → approval gate]  │
│  ├── MCP github         (http://localhost:8002/mcp, our FastMCP server)        │
│  │     branch/push/PR tools (NOT approval-gated — reversible)                 │
│  └── sandbox: Daytona (Python, Postgres in-sandbox, repo checkout at          │
│        /workspace, schemaforge_core + demo-app)                               │
│                                                                               │
│  Subagents (parallel, dynamic_sub_agents):                                    │
│    • db-analysis:   drives postgres-prod MCP  → JSON snapshot summary         │
│    • code-analysis: runs schemaforge_core in sandbox → facts/graph/mermaid    │
└───────────────────────────────────────────────────────────────────────────────┘
        │ deterministic core (pure Python, no LLM)
        ▼
schemaforge_core:  db_snapshot → code_facts (ast + sqlparse) → impact_graph
                   → pipeline verify (alembic upgrade, parity SQL, pytest,
                   EXPLAIN ANALYZE bench) → safety report (markdown)
        │
        ▼  approval gate (harness pauses on tool.approval_required)
postgres-prod.execute_ddl(migration SQL)   ← human approves in chat UI
        │
        ▼
GitHub MCP: push_files + create_pull_request (migration + refactored code)
```

**Key design principles (from the review of the original PDF):**
1. **Analysis is deterministic.** The LLM never parses the codebase or counts rows.
   `schemaforge_core` (Python `ast` + `sqlparse` + `pg_catalog`) produces the facts;
   the LLM plans, orchestrates, and explains *over* the graph.
2. **Two databases.** "Production" = a local Docker Postgres (port 5433) with real
   seed volume; the sandbox runs its own in-sandbox Postgres (port 5432). The
   irreversible, gated action is `execute_ddl` against prod. Sandbox work is never
   gated (it's throwaway).
3. **The gate is native.** TrueForge resolves MCP tool annotations
   (`destructiveHint`) to the `@destructive` selector, which matches the verified
   default `require_approval_for_tools: ["@write","@destructive"]` on the
   postgres-prod MCP server entry. No custom approval plumbing.
4. **One narrow demo slice.** Python + SQLAlchemy 2.0 + FastAPI app, Postgres,
   one migration pattern: `users → users + user_profiles` (1:1 split,
   expand → backfill → contract).
5. **A golden reference path exists in-repo** (`reference/post-split/`) so the
   agent's autonomous output can be diffed against a known-good result, and the
   demo has a scripted fallback if the agent stalls.

## Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Harness | TrueForge local (`npx @truefoundry/trueforge`, port 8790, API v0.1.4) | Already installed & running; Daytona sandbox + model provider configured |
| Model | Local llama.cpp server (`http://localhost:8000/v1`) as a `custom` provider | `qwen3.8-27b` (GGUF Q4_K, thinking model); auto-discovered by `scripts/setup_local_model.py` |
| Sandbox | Daytona (cloud), configured as TrueForge's sandbox provider | API key in `.env` (`DAYTONA_API_KEY`); Daytona CLI (`daytona`) for the Day-2 rehearsal (9.5) |
| DB | PostgreSQL 16 (Docker for prod/dev; apt in sandbox) | `psycopg` 3 (binary) everywhere |
| ORM / migrations | SQLAlchemy 2.0, Alembic | Demo app + golden migration |
| Analysis core | Python stdlib `ast` + `sqlparse` + `pg_catalog` queries | No tree-sitter (scope is Python-only) |
| MCP (ours) | `mcp` Python SDK, `FastMCP`, streamable HTTP | `mcp-servers/postgres-mcp/server.py` |
| MCP (GitHub) | in-repo FastMCP server (`mcp-servers/github-mcp/server.py`), port 8002 | PAT from env (header auth) |
| Python | 3.14, repo venv `.vevn/` (uv-managed, no pip module) | install via `uv pip install --python .vevn/bin/python` |
| Review | Qodo via GitHub integration | every PR → Qodo review → fix Highs → merge |

## Global Constraints

- **Qodo:** every task that changes code produces a branch + PR; Qodo reviews;
  High findings are fixed or explicitly dismissed with a reason; only then merge.
  One repo installation is enough. If Qodo is silent on a PR: comment `/agentic_review`.
- **No secrets in the repo.** `.env` (gitignored) holds: `LLM_BASE_URL`
  (local llama.cpp — no key needed), `DAYTONA_API_KEY` (sandbox provider),
  `GITHUB_PERSONAL_ACCESS_TOKEN`,
  `DATABASE_URL` (prod = `postgresql://postgres:postgres@localhost:5433/bookstore`),
  `TRUEFORGE_URL=http://localhost:8790`, `POSTGRES_MCP_URL`, `GITHUB_MCP_URL`,
  `SCHEMAFORGE_MODEL`. `.env.example` lists them empty.
- **Approval gate invariant:** the only prod write path is
  `postgres-prod.execute_ddl`, which (a) only accepts DDL verbs, (b) is annotated
  `destructiveHint: true`, and (c) has no approval exemption in the agent spec.
  The gate is configured exactly once — in `scripts/apply_agent.py`'s manifest
  (`require_approval_for_tools`); `agent/instructions.md` and the README
  *describe* the behavior and must not restate the config values, so the
  three copies cannot drift.
- **`main` stays pre-split.** The demo-app on main is the migration *source* state.
  Post-split code lives only in `reference/post-split/` (artifact, not wired in)
  and on the agent's PR branch.
- **Determinism:** core modules are pure functions of (snapshot JSON, source tree);
  the same inputs must produce identical JSON/mermaid outputs (tests assert this).
- **Hackathon rules:** open-source repo, built during the week, runs on TrueForge,
  submission = public repo + ~3 min demo video + short write-up. Connect only data
  you own (local Docker DB + your own repo).
- **TrueForge spec facts below are verified against the live install's
  `GET /api/v1/openapi.json` (v0.1.4)** — treat them as ground truth, not docs.

### Verified harness reference (live install, API v0.1.4)

- `AgentSpec`: only `model` required; optional `instructions`, `messages`,
  `mcp_servers`, `response_format`, `skills`, `config`.
- `MCPServerManifest` (configured): `type` (only `"remote"`), `name`, `url`,
  `description` (minLength 1), `auth`.
- Agent `mcp_servers` entry defaults: `enable_tools ["@all"]`,
  `disable_tools []`, `preload_tools []`,
  `require_approval_for_tools ["@write","@destructive"]`, `preload false`.
- `RuntimeConfig` defaults: `iteration_limit 100` (1–1024),
  `sandbox.enabled false`, `dynamic_sub_agents.enabled true`,
  `context_management.compaction.enabled true`,
  `context_management.large_tool_response.enabled true`,
  `generative_ui.enabled true`, `ask_user_questions.enabled true`.
- `CreateTurnRequest`: `input: TurnInputItem[]`, `previous_turn_id`,
  `stream` (default true). `UserMessage`: `{type: "user.message",
  content: string | [TextContent|FileContent]}`.
- Approval resume: `user.tool_approval` `{type, thread_id, tool_call_id,
  approval: {status: "allow"|"deny", reason?}}`. A turn's input array must not
  mix `user.message` with approval/response items.
- `ResourceName`: `^[a-z](?:[a-z0-9._-]{0,62}[a-z0-9])$` → model/agent/server/skill
  names must be lowercase-leading, no `/`.
- `ConfiguredModel`: requires `model_id`, `name` (ResourceName), `properties`
  (`{}` is valid — all ModelProperties fields optional).
- Custom model provider manifest: `{type: "custom", name, base_url, auth:
  {api_key}, models: [ConfiguredModel]}` — PUT is full-replace; a redacted
  `api_key` in the PUT body keeps the stored secret.
- Skill manifest: git-backed `{type: "git", url, ref, path?, description?}`,
  name pattern `^[A-Za-z0-9._-]+$`, max 64.
- Sessions: `POST /api/v1/sessions` with `{agent: {name}}` or `{agent: {spec}}`;
  `POST .../turns`; events via SSE `.../turns/{id}/subscribe`
  (`after_sequence_number` exclusive cursor) or `GET .../turns/{id}/events`.
- `GET /api/v1/capabilities` → `{sandbox.enabled, settings.enabled, skill.enabled}`.

---

## Repository layout (target)

```
schemaforge/
├── README.md                        # final: pitch, run instructions, Qodo evidence
├── .env.example
├── .gitignore                       # add .vevn/, .env, out/, *.log
├── docs/superpowers/plans/2026-08-26-schemaforge-hackathon.md   (this file)
├── core/                            # deterministic engine (editable-installed)
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── schemaforge_core/
│   │   ├── __init__.py
│   │   ├── __main__.py
│   │   ├── models.py
│   │   ├── db_snapshot.py
│   │   ├── code_facts.py
│   │   ├── impact_graph.py
│   │   ├── pipeline.py
│   │   └── report.py
│   └── tests/
│       ├── __init__.py
│       ├── test_diff_tables.py
│       ├── test_code_facts.py
│       ├── test_impact_graph.py
│       └── test_queries_parser.py
├── demo-app/                        # migration SOURCE state (FastAPI+SQLAlchemy)
│   ├── requirements.txt
│   ├── docker-compose.dev.yml
│   ├── init-dev.sql
│   ├── alembic.ini
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py
│   │   ├── db.py
│   │   ├── models.py
│   │   └── routers/
│   │       ├── __init__.py
│   │       ├── users.py
│   │       └── reports.py
│   ├── alembic/
│   │   ├── env.py
│   │   ├── script.py.mako
│   │   └── versions/0001_initial.py
│   ├── queries/bench.sql
│   ├── seed.py
│   └── tests/
│       ├── __init__.py
│       ├── conftest.py
│       └── test_users.py
├── reference/post-split/            # golden outcome (NOT wired to demo-app)
│   ├── README.md
│   ├── alembic/versions/0002_split_users.py
│   ├── app/models.py
│   ├── app/routers/users.py
│   ├── app/routers/reports.py
│   └── parity.sql
├── mcp-servers/
│   ├── postgres-mcp/
│   │   ├── requirements.txt
│   │   └── server.py
│   └── github-mcp/
│       ├── requirements.txt
│       └── server.py
├── skills/
│   └── schemaforge-migration/
│       └── SKILL.md
├── agent/
│   └── instructions.md
├── scripts/
│   ├── setup_local_model.py
│   ├── apply_agent.py
│   ├── import_skill.py
│   ├── run_mcp_servers.sh
│   ├── sandbox_setup.sh
│   ├── prod-postgres/docker-compose.yml
│   ├── seed_prod.sh
│   └── demo.py                      # reproducible API-driven session (stretch)
└── out/                             # generated artifacts (gitignored)
```

---

# Day 0 — Aug 26 (today) · Foundations

## Task 1 — Repo hygiene, public GitHub repo, Qodo (PR #1)

**Goal:** a public repo on `main` that Qodo can review, with the scaffold for
scripts, `.env.example`, and the plan doc committed.

Steps:
- [ ] 1.1 Update `.gitignore` (current file ignores `.venv` but the venv is
  `.vevn` — add both, plus env/artifacts):

```gitignore
# Python
__pycache__/
*.py[cod]
.vevn/
.venv/

# secrets
.env

# generated artifacts
out/
*.log
node_modules/

# OS
.DS_Store
```

- [ ] 1.2 Create `.env.example` (exact contents — values stay out of git):

```dotenv
# TrueForge instance (local mode)
TRUEFORGE_URL=http://localhost:8790

# Local LLM (llama.cpp, OpenAI-compatible) — no key needed
LLM_BASE_URL=http://localhost:8000/v1

# "Production" Postgres (local docker, port 5433) — owned demo data only
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/bookstore

# MCP servers (local processes)
POSTGRES_MCP_URL=http://localhost:8001/mcp
GITHUB_MCP_URL=http://localhost:8002/mcp
GITHUB_PERSONAL_ACCESS_TOKEN=

# Daytona sandbox provider (cloud; key from app.daytona.io/dashboard/keys)
DAYTONA_API_KEY=

# Agent model (FQN = provider/model)
SCHEMAFORGE_MODEL=local/qwen3.8-27b
```

- [ ] 1.3 Create `docs/superpowers/plans/2026-08-26-schemaforge-hackathon.md`
  (this plan — already written).
- [ ] 1.4 Create empty dirs with the scaffold files that this task owns:
  `scripts/.gitkeep` (removed once real scripts land), keep existing
  `mcp-servers/`, `skills/` dirs (populated in later PRs).
- [ ] 1.5 Rename branch and push (repo already `git init`ed on branch `Utsav`):

```bash
cd /home/utsav/Github/schemaforge
git branch -m main
git add -A
git commit -m "chore: repo hygiene, env template, implementation plan"
gh auth status || gh auth login
gh repo create schemaforge --public --source=. --remote=origin
```

  (If `gh` isn't installed, create the empty public repo on github.com and
  `git remote add origin https://github.com/<you>/schemaforge.git && git push -u origin main`.)

- [ ] 1.6 Set `main` as the default branch on GitHub (repo → Settings → General).
- [ ] 1.7 Qodo install: sign in at app.qodo.ai (repo admin) → Integrations →
  SaaS → GitHub → Add installation (covers the new repo).
- [ ] 1.8 Open **PR #1** (branch `chore/repo-hygiene` off `main`, containing
  1.1–1.4 — push the commit to the branch *before* creating the PR, i.e.
  rebase the commit onto a fresh branch: `git checkout -b chore/repo-hygiene`
  *before* `git commit`, then `git push origin chore/repo-hygiene` + `gh pr create`).

  **Acceptance:** PR #1 shows a Qodo review (wait ~2 min; if silent, comment
  `/agentic_review`). No High findings expected. Merge. `main` is the default
  branch, repo is public.

## Task 2 — TrueForge verification + local llama.cpp model registration (no PR; config)

**Goal:** confirm the live install's capabilities, then register the local
llama.cpp server (`http://localhost:8000/v1`, model `qwen3.8-27b`) with
TrueForge as a `custom` OpenAI-compatible provider.

Steps:
- [ ] 2.1 Check the instance is up, read capabilities, and confirm the
  Daytona sandbox provider is configured and healthy:

```bash
curl -s http://localhost:8790/api/v1/capabilities
# expect: {"sandbox":{"enabled":true},"settings":{"enabled":true},"skill":{"enabled":true}}
# (skill.enabled is false iff sandbox is off — it must be true for us)
curl -s http://localhost:8790/api/v1/settings/sandbox-providers | python3 -m json.tool
# expect: the single provider, type "daytona", status "ready", api_key redacted
```

  If unconfigured or status is not `ready`, register it (`$DAYTONA_API_KEY`
  is exported in `~/.zshrc`; mirror it into `.env` for portability):

```bash
curl -s -X PUT http://localhost:8790/api/v1/settings/sandbox-providers \
  -H 'content-type: application/json' \
  -d '{"manifest":{"type":"daytona","auth":{"api_key":"'"$DAYTONA_API_KEY"'"},
"exec_timeout_ms":120000,"auto_stop":30,"auto_archive":1440,"auto_delete":10080}}'
# verified manifest schema: type, auth.api_key, exec_timeout_ms (>0),
# auto_stop/auto_archive/auto_delete in minutes (0 disables)
```

- [ ] 2.2 Confirm the local model server answers:

```bash
curl -s http://localhost:8000/v1/models | python3 -m json.tool
# expect data[0].id == "qwen3.8-27b" (owned_by "llamacpp")
```

- [ ] 2.3 Write `scripts/setup_local_model.py` (full code below) and run it:

```bash
set -a; source .env; set +a
.vevn/bin/python scripts/setup_local_model.py
```

- [ ] 2.4 Verify the FQN is registered:

```bash
curl -s http://localhost:8790/api/v1/models | python3 -m json.tool
# expect local/qwen3.8-27b
```

- [ ] 2.5 Smoke-test the model through the harness: create a one-shot session
  on `local/qwen3.8-27b`, send "Reply with exactly: OK", and expect `OK` in
  the final `model.message`. (`curl -s -X POST $TRUEFORGE_URL/api/v1/sessions
  -H 'content-type: application/json' -d '{"agent":{"spec":{"model":{"name":"local/qwen3.8-27b"}}}}'`,
  then POST a turn with `stream:false` and `GET` the turn until
  `state.status=done`.) Note: this is a thinking model (responses carry
  `reasoning_content`) — a tiny token cap can yield empty visible content;
  the harness's normal limits are fine.

- [ ] 2.6 Measure a baseline tok/s and record it in the Day-3 notes (it sets
  the video plan — live vs. pre-recorded):

```bash
time curl -s http://localhost:8000/v1/chat/completions \
  -H 'content-type: application/json' \
  -d '{"model":"qwen3.8-27b","messages":[{"role":"user","content":"Write a short haiku about databases."}],"max_tokens":128}' \
  -o /tmp/sf_tps.json
# tok/s ≈ 128 / (wall seconds); log it next to the Day-3 rehearsal
```

**`scripts/setup_local_model.py`:**

```python
"""Register the local llama.cpp server as a TrueForge custom model provider.

Auto-discovers models via GET {LLM_BASE_URL}/models so swapping GGUFs later
needs no code change. PUT /api/v1/settings/model-providers is create-or-
replace keyed by provider name; llama.cpp ignores auth, so a dummy api_key
is sent (the schema requires one).
"""
from __future__ import annotations

import json
import os
import re
import sys

import httpx

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:8000/v1")
PROVIDER = "local"


def to_resource_name(model_id: str) -> str:
    """Map an upstream model id onto the ResourceName pattern."""
    name = re.sub(r"[^a-z0-9._-]", "-", model_id.lower().replace("/", "-"))
    name = name.strip("-._") or "model"
    if not name[0].isalpha():
        name = "m-" + name
    return name[:64]


def main() -> None:
    with httpx.Client(timeout=30) as client:
        r = client.get(f"{LLM_BASE_URL}/models")
        if r.status_code >= 400:
            sys.exit(f"local model server unreachable: {r.status_code} {r.text[:200]}")
        ids = [m["id"] for m in r.json().get("data", [])]
        if not ids:
            sys.exit(f"no models served at {LLM_BASE_URL}/models")
        models = [
            {"model_id": mid, "name": to_resource_name(mid), "properties": {}}
            for mid in ids
        ]
        manifest = {
            "type": "custom",
            "name": PROVIDER,
            "base_url": LLM_BASE_URL,
            "auth": {"api_key": "llamacpp"},  # ignored by the server
            "models": models,
        }
        resp = client.put(
            f"{BASE}/api/v1/settings/model-providers", json={"manifest": manifest}
        )
    if resp.status_code >= 400:
        sys.exit(f"model-provider update failed: {resp.status_code} {resp.text}")
    print(json.dumps(resp.json(), indent=2))
    print("\nFQNs now available:")
    for m in models:
        print(f"  {PROVIDER}/{m['name']}")


if __name__ == "__main__":
    main()
```

**Acceptance:** `GET /api/v1/models` lists `local/qwen3.8-27b`; a one-shot
harness conversation on it returns `OK`; the tok/s baseline is recorded. The
script lands in the same branch/PR as Task 3 (PR #2) so it's Qodo-reviewed
like everything else.

## Task 3 — Postgres MCP server + prod DB + runner scripts (PR #2)

**Goal:** our own MCP server over the "production" Postgres with a
destructive-annotated `execute_ddl` (the approval-gated tool), the prod Postgres
in Docker, seed scripts, and a runner that starts both MCP servers.

Steps:
- [ ] 3.1 `scripts/prod-postgres/docker-compose.yml`:

```yaml
services:
  prod-db:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: bookstore
    ports:
      - "5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres -d bookstore"]
      interval: 2s
      timeout: 2s
      retries: 10
volumes:
  prod-data:
    driver: local
```

  (Re-declare `volumes: prod-data` and mount `prod-data:/var/lib/postgresql/data`
  under `prod-db` if you want persistence; for the hackathon, a fresh container
  each run is actually preferable — drop the volume, keep the name in the file
  for clarity.)

- [ ] 3.2 `scripts/seed_prod.sh` (idempotent; applies 0001 + seeds 200k rows):

```bash
#!/usr/bin/env bash
# Seed the "production" bookstore DB (docker, port 5433) with the pre-split
# schema and 200,000 users / 5,000 books so EXPLAIN ANALYZE is meaningful.
set -euo pipefail
cd "$(dirname "$0")/.."

export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5433/bookstore}"

echo "applying alembic baseline (0001)..."
(cd demo-app && DATABASE_URL="$DATABASE_URL" .vevn/bin/alembic upgrade head 2>/dev/null \
  || (cd demo-app && DATABASE_URL="$DATABASE_URL" alembic upgrade head))

echo "seeding..."
(cd demo-app && DATABASE_URL="$DATABASE_URL" .vevn/bin/python seed.py 200000 5000)

echo "row counts:"
psql "$DATABASE_URL" -Atc "SELECT 'users='||count(*) FROM users" || \
  .vevn/bin/python -c "import psycopg,os; print(psycopg.connect(os.environ['DATABASE_URL']).execute('SELECT count(*) FROM users').fetchone())"
```

  (Note: at this point `demo-app/` doesn't exist yet — seed_prod.sh is only run
  after Task 4 lands. It's committed now as part of the scripts scaffold; Qodo
  reviews it as a shell script.)

- [ ] 3.3 `mcp-servers/postgres-mcp/requirements.txt`:

```
mcp>=1.9
psycopg[binary]>=3.2
uvicorn>=0.30
```

- [ ] 3.4 `mcp-servers/postgres-mcp/server.py` (full code):

```python
"""SchemaForge production-Postgres MCP server.

Exposes read-only introspection tools and exactly one write tool,
`execute_ddl`, annotated destructiveHint so TrueForge's approval gate pauses
before it runs (require_approval_for_tools default matches @destructive).
The only prod write path in the whole system is this tool.
"""
from __future__ import annotations

import os
import re

import psycopg
from mcp.server.fastmcp import FastMCP
from psycopg.rows import dict_row

DSN = os.environ["DATABASE_URL"]  # prod DB, e.g. postgresql://postgres:postgres@localhost:5433/bookstore

_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")
_ALLOWED_DDL = re.compile(
    r"^\s*(CREATE|ALTER|DROP|TRUNCATE|COMMENT|GRANT|REVOKE)\b", re.IGNORECASE
)
_FORBIDDEN = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|COPY|VACUUM|REINDEX)\b", re.IGNORECASE
)

mcp = FastMCP("postgres-prod")


def _conn() -> psycopg.Connection:
    return psycopg.connect(DSN, row_factory=dict_row, autocommit=True)


def _check_ident(name: str) -> None:
    if not _IDENT.match(name):
        raise ValueError(f"invalid identifier: {name!r}")


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def list_tables() -> list[str]:
    """All tables in the public schema, sorted."""
    with _conn() as conn:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
            "ORDER BY table_name"
        ).fetchall()
    return [r["table_name"] for r in rows]


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def table_schema(table: str) -> dict:
    """Columns (name/type/nullable), primary key, and foreign keys for one table."""
    _check_ident(table)
    with _conn() as conn:
        cols = conn.execute(
            "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
            (table,),
        ).fetchall()
        pks = conn.execute(
            "SELECT a.attname FROM pg_index i "
            "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
            "WHERE i.indrelid = %s::regclass AND i.indisprimary ORDER BY array_position(i.indkey, a.attnum)",
            (table,),
        ).fetchall()
        fks = conn.execute(
            "SELECT tc.constraint_name, kcu.column_name, ccu.table_name AS ref_table, "
            "ccu.column_name AS ref_column "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "  ON tc.constraint_name = ccu.constraint_name AND tc.table_schema = ccu.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = %s",
            (table,),
        ).fetchall()
    return {"table": table, "columns": cols, "primary_key": [r["attname"] for r in pks], "foreign_keys": fks}


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def row_count(table: str) -> int:
    """Exact row count for one table (O(n) scan — fine at demo scale)."""
    _check_ident(table)
    with _conn() as conn:
        return conn.execute(f'SELECT count(*) FROM "{table}"').fetchone()["count"]


@mcp.tool(annotations={"readOnlyHint": True, "openWorldHint": False})
def explain(sql: str) -> str:
    """EXPLAIN (no ANALYZE) for a SELECT — never executes writes or heavy scans on prod."""
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise ValueError("explain() only accepts SELECT statements")
    with _conn() as conn:
        rows = conn.execute(f"EXPLAIN {sql}").fetchall()
    return "\n".join(r["QUERY PLAN"] for r in rows)


@mcp.tool(
    annotations={"destructiveHint": True, "idempotentHint": False, "openWorldHint": False},
    description=(
        "Execute DDL (CREATE/ALTER/DROP/...) against the production database. "
        "Irreversible — the harness pauses this call for human approval."
    ),
)
def execute_ddl(sql: str) -> str:
    """Run a DDL statement or semicolon-separated DDL batch against prod."""
    if _FORBIDDEN.search(sql):
        raise ValueError("only DDL is allowed here (no SELECT/INSERT/UPDATE/DELETE/COPY)")
    statements = [s for s in sql.split(";") if s.strip()]
    if not statements:
        raise ValueError("empty DDL batch")
    for stmt in statements:
        if not _ALLOWED_DDL.match(stmt):
            raise ValueError(f"statement not allowed by execute_ddl: {stmt[:80]!r}")
    with _conn() as conn:
        for stmt in statements:
            conn.execute(stmt)
    return f"executed {len(statements)} DDL statement(s) against prod"


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8001)
```

- [ ] 3.5 `scripts/run_mcp_servers.sh`:

```bash
#!/usr/bin/env bash
# Start both MCP servers that TrueForge connects to (localhost:8001, localhost:8002).
set -uo pipefail
cd "$(dirname "$0")/.."

# load .env
if [ -f .env ]; then set -a; . ./.env; set +a; fi
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgres@localhost:5433/bookstore}"

.vevn/bin/python -m pip install -q -r mcp-servers/postgres-mcp/requirements.txt 2>/dev/null \
  || uv pip install --python .vevn/bin/python -q -r mcp-servers/postgres-mcp/requirements.txt

echo "[postgres-mcp] starting on :8001"
.vevn/bin/python mcp-servers/postgres-mcp/server.py &
PG_PID=$!

echo "[github-mcp] starting on :8002 (uvx first run may take a minute)"
GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:?set in .env}" \
  uvx --from git+https://github.com/GongRzhe/Github-MCP-Server \
  github-mcp-server --transport http --port 8002 &
GH_PID=$!
# install deps (pip when available in the venv, else uv)
for req in mcp-servers/postgres-mcp/requirements.txt mcp-servers/github-mcp/requirements.txt; do
  .vevn/bin/python -m pip install -q -r "$req" 2>/dev/null \
    || uv pip install --python .vevn/bin/python -q -r "$req"
done

echo "[postgres-mcp] starting on :8001"
.vevn/bin/python mcp-servers/postgres-mcp/server.py &
PG_PID=$!

echo "[github-mcp] starting on :8002"
GITHUB_PERSONAL_ACCESS_TOKEN="${GITHUB_PERSONAL_ACCESS_TOKEN:?set in .env}" \
  .vevn/bin/python mcp-servers/github-mcp/server.py &
GH_PID=$!

wait
```

- [ ] 3.6 Smoke-test the postgres MCP locally:

```bash
docker compose -f scripts/prod-postgres/docker-compose.yml up -d
.vevn/bin/python - <<'EOF'
import os
os.environ["DATABASE_URL"] = "postgresql://postgres:postgres@localhost:5433/bookstore"
import psycopg
c = psycopg.connect(os.environ["DATABASE_URL"])
c.autocommit = True
c.execute("CREATE TABLE IF NOT EXISTS _mcp_probe (id int)")
print("prod db reachable")
EOF
# start server, then:
DATABASE_URL=postgresql://postgres:postgres@localhost:5433/bookstore \
  .vevn/bin/python mcp-servers/postgres-mcp/server.py &
sleep 2
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8001/mcp   # expect 200/405/406 = alive
```

  (Register it in TrueForge UI: Settings → Connectors → add `postgres-prod` at
  `http://localhost:8001/mcp`, no auth. Then in a chat, ask a scratch agent to
  call `list_tables` — you should see the probe table. The same UI step
  registers `github` at `http://localhost:8002/mcp` with header auth
  `Authorization: Bearer <PAT>` if the server needs it, else none.)

- [ ] 3.7 Branch `feat/mcp-servers`, commit, push, **PR #2** with description:
  what the server exposes, why `execute_ddl` is the only write path and how the
  annotation drives the approval gate. Wait for Qodo, resolve Highs, merge.

**Acceptance:** prod Postgres up on 5433; `curl` shows 8001 alive; `list_tables`
answers through TrueForge; PR #2 merged with Qodo review.

---

# Day 1 — Aug 27 · Deterministic core

## Task 4 — demo-app: the migration source state (PR #3)

**Goal:** a running FastAPI + SQLAlchemy 2.0 bookstore API on Postgres with
Alembic baseline, seed script, and a green test suite that encodes the API
contract (which the post-split code must still satisfy).

Steps:
- [ ] 4.1 `demo-app/requirements.txt`:

```
fastapi>=0.115
uvicorn[standard]>=0.30
sqlalchemy>=2.0.30
psycopg[binary]>=3.2
alembic>=1.13
pytest>=8.2
httpx>=0.27
```

  Install: `uv pip install --python .vevn/bin/python -r demo-app/requirements.txt`

- [ ] 4.2 Dev Postgres for local TDD: `demo-app/docker-compose.dev.yml` +
  `demo-app/init-dev.sql`:

```yaml
services:
  dev-db:
    image: postgres:16
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
    ports:
      - "5434:5432"
    volumes:
      - ./init-dev.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 2s
      timeout: 2s
      retries: 10
```

```sql
CREATE DATABASE bookstore;
CREATE DATABASE bookstore_test;
```

  Run: `cd demo-app && docker compose -f docker-compose.dev.yml up -d`

- [ ] 4.3 `demo-app/app/__init__.py` and `demo-app/app/routers/__init__.py`
  (empty files).

- [ ] 4.4 `demo-app/app/db.py`:

```python
import os

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://postgres:postgres@localhost:5434/bookstore"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
```

- [ ] 4.5 `demo-app/app/models.py` (pre-split — this is the state the agent
  migrates FROM):

```python
from sqlalchemy import String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(100))
    price_cents: Mapped[int] = mapped_column()
```

- [ ] 4.6 `demo-app/app/routers/users.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import User

router = APIRouter(prefix="/users", tags=["users"])


class UserIn(BaseModel):
    name: str
    email: str
    address: str
    date_of_birth: str | None = None


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    address: str
    date_of_birth: str | None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def to_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        address=user.address,
        date_of_birth=user.date_of_birth,
    )


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    return [to_out(u) for u in db.query(User).order_by(User.id).all()]


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="user not found")
    return to_out(user)


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    user = User(**payload.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return to_out(user)
```

- [ ] 4.7 `demo-app/app/routers/reports.py` (raw SQL — gives the impact graph
  a `queries → users` edge):

```python
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import SessionLocal

router = APIRouter(prefix="/reports", tags=["reports"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/addresses")
def user_addresses(db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT u.name, u.address FROM users u ORDER BY u.id LIMIT 20")
    ).fetchall()
    return [{"name": r.name, "address": r.address} for r in rows]
```

- [ ] 4.8 `demo-app/app/main.py`:

```python
from fastapi import FastAPI

from .routers import reports, users

app = FastAPI(title="Bookstore API")
app.include_router(users.router)
app.include_router(reports.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
```

- [ ] 4.9 Alembic. `demo-app/alembic.ini`:

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql://postgres:postgres@localhost:5434/bookstore
prepend_sys_path = .

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
```

  `demo-app/alembic/env.py` (standard online/offline):

```python
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.models import Base  # noqa: E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.", poolclass=pool.NullPool, url=url,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

  `demo-app/alembic/script.py.mako` (Alembic default template):

```mako
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

  `demo-app/alembic/versions/0001_initial.py`:

```python
"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-27

"""
from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.String(length=10), nullable=True),
        sa.UniqueConstraint("email"),
    )
    op.create_table(
        "books",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("author", sa.String(length=100), nullable=False),
        sa.Column("price_cents", sa.Integer(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("books")
    op.drop_table("users")
```

- [ ] 4.10 `demo-app/seed.py`:

```python
"""Seed the bookstore DB. Usage: DATABASE_URL=... python seed.py [users] [books]"""
import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Book, User

users_n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
books_n = int(sys.argv[2]) if len(sys.argv) > 2 else 3

engine = create_engine(os.environ["DATABASE_URL"])
Session = sessionmaker(bind=engine)

with Session() as s:
    if s.query(User).count() == 0:
        s.add_all(
            User(
                name=f"user{i}",
                email=f"user{i}@example.com",
                address=f"{i} Main St",
                date_of_birth="1990-01-01" if i % 2 == 0 else None,
            )
            for i in range(users_n)
        )
    if s.query(Book).count() == 0:
        s.add_all(
            Book(
                title=f"Book {i}",
                author=f"Author {i % 7}",
                price_cents=999 + i,
            )
            for i in range(books_n)
        )
    s.commit()

print(f"seeded: users={s.query(User).count()}, books={s.query(Book).count()}")
```

- [ ] 4.11 `demo-app/queries/bench.sql` (the queries the EXPLAIN bench runs):

```sql
-- name: find_by_email
SELECT id, name, email FROM users WHERE email = 'user1@example.com';

-- name: recent_users
SELECT id, name FROM users ORDER BY id DESC LIMIT 20;

-- name: addresses_report
SELECT u.name, u.address FROM users u ORDER BY u.id LIMIT 20;
```

- [ ] 4.12 `demo-app/tests/__init__.py` (empty) and `demo-app/tests/conftest.py`:

```python
import os

# Force the app onto the test database BEFORE app is imported (db.py reads env).
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5434/bookstore_test",
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from app.main import app  # noqa: E402
from app.models import Base, User  # noqa: E402


@pytest.fixture(scope="session")
def client():
    engine = create_engine(TEST_DATABASE_URL)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as s:
        if not s.query(User).first():
            s.add_all(
                [
                    User(name="Ada", email="ada@example.com", address="1 Main St",
                         date_of_birth="1990-01-01"),
                    User(name="Bob", email="bob@example.com", address="2 Side St",
                         date_of_birth=None),
                ]
            )
            s.commit()
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(engine)
    engine.dispose()
```

- [ ] 4.13 `demo-app/tests/test_users.py` — the **contract** the post-split
  code must keep satisfying:

```python
def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_list_users_shape(client):
    r = client.get("/users")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 2
    for item in data:
        # exact key set = the API contract the split must preserve
        assert set(item) == {"id", "name", "email", "address", "date_of_birth"}
    assert data[0]["name"] == "Ada"
    assert data[0]["address"] == "1 Main St"
    assert data[1]["date_of_birth"] is None


def test_get_user(client):
    r = client.get("/users/1")
    assert r.status_code == 200
    assert r.json()["email"] == "ada@example.com"


def test_get_user_404(client):
    assert client.get("/users/999").status_code == 404


def test_create_user(client):
    r = client.post(
        "/users",
        json={"name": "Carol", "email": "carol@example.com",
              "address": "3 Third St", "date_of_birth": "1995-05-05"},
    )
    assert r.status_code == 201
    assert set(r.json()) == {"id", "name", "email", "address", "date_of_birth"}


def test_reports_addresses(client):
    r = client.get("/reports/addresses")
    assert r.status_code == 200
    body = r.json()
    assert body[0] == {"name": "Ada", "address": "1 Main St"}
```

- [ ] 4.14 Run the baseline locally:

```bash
cd /home/utsav/Github/schemaforge
cd demo-app
DATABASE_URL=postgresql://postgres:postgres@localhost:5434/bookstore \
  ../.vevn/bin/alembic upgrade head
DATABASE_URL=postgresql://postgres:postgres@localhost:5434/bookstore \
  ../.vevn/bin/python seed.py
cd ..
.vevn/bin/pytest demo-app/tests -q        # expect 6 passed
```

- [ ] 4.15 Branch `feat/demo-app`, commit, push, **PR #3**: description includes
  the API contract rationale ("tests encode the response shape the migration
  must preserve"). Qodo → resolve → merge.

**Acceptance:** 6/6 tests green; `alembic upgrade head` clean; `curl
localhost:8000/users` (uvicorn) returns the 2 seeded users; PR #3 merged.

## Task 5 — core: data model + db_snapshot (PR #4)

Steps:
- [ ] 5.1 `core/pyproject.toml`:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "schemaforge-core"
version = "0.1.0"
description = "Deterministic analysis engine for SchemaForge (DB snapshot + code facts + impact graph)"
requires-python = ">=3.11"
dependencies = [
    "psycopg[binary]>=3.2",
    "sqlparse>=0.5",
]

[project.scripts]
sf-pipeline = "schemaforge_core.pipeline:main"

[tool.setuptools.packages.find]
include = ["schemaforge_core*"]
```

- [ ] 5.2 `core/requirements.txt`:

```
psycopg[binary]>=3.2
sqlparse>=0.5
```

- [ ] 5.3 `core/schemaforge_core/__init__.py` (empty),
  `core/schemaforge_core/models.py` (full code):

```python
"""SchemaForge core data model: DB snapshot, code facts, impact graph.

All types are plain dataclasses with to_dict/from_dict so the pipeline can
pass everything between stages as JSON (and the LLM can read it).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    default: str | None = None


@dataclass
class IndexInfo:
    name: str
    columns: list[str] = field(default_factory=list)
    unique: bool = False


@dataclass
class ForeignKeyInfo:
    name: str
    column: str
    ref_table: str
    ref_column: str


@dataclass
class TableInfo:
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    indexes: list[IndexInfo] = field(default_factory=list)
    foreign_keys: list[ForeignKeyInfo] = field(default_factory=list)
    row_count: int | None = None  # pg_class.reltuples estimate


@dataclass
class DBSnapshot:
    tables: dict[str, TableInfo] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> DBSnapshot:
        snap = cls()
        for name, t in d.get("tables", {}).items():
            snap.tables[name] = TableInfo(
                name=t["name"],
                columns=[ColumnInfo(**c) for c in t["columns"]],
                indexes=[IndexInfo(**i) for i in t["indexes"]],
                foreign_keys=[ForeignKeyInfo(**f) for f in t["foreign_keys"]],
                row_count=t.get("row_count"),
            )
        return snap


@dataclass
class ModelFact:
    """A SQLAlchemy declarative model class (name ↔ table mapping)."""

    name: str
    table: str
    columns: list[str]
    file: str
    line: int


@dataclass
class AttrAccess:
    """An attribute read of a known model column on a model-typed variable."""

    model: str
    column: str
    file: str
    line: int
    function: str


@dataclass
class RawSqlRef:
    """A raw SQL string (text(...) / execute(...)) and the tables it touches."""

    tables: list[str]
    file: str
    line: int
    function: str


@dataclass
class EndpointFact:
    """A FastAPI route."""

    path: str
    method: str
    file: str
    line: int
    function: str


@dataclass
class CodeFacts:
    models: list[ModelFact] = field(default_factory=list)
    attr_accesses: list[AttrAccess] = field(default_factory=list)
    raw_sql: list[RawSqlRef] = field(default_factory=list)
    endpoints: list[EndpointFact] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> CodeFacts:
        return cls(
            models=[ModelFact(**m) for m in d.get("models", [])],
            attr_accesses=[AttrAccess(**a) for a in d.get("attr_accesses", [])],
            raw_sql=[RawSqlRef(**r) for r in d.get("raw_sql", [])],
            endpoints=[EndpointFact(**e) for e in d.get("endpoints", [])],
        )


@dataclass
class ImpactNode:
    id: str
    kind: str  # table | column | model | attr | rawsql | endpoint
    label: str
    file: str | None = None


@dataclass
class ImpactEdge:
    src: str
    dst: str
    kind: str  # has_column | maps_to | defines_column | accessed_via | queries | executes


@dataclass
class ImpactGraph:
    nodes: dict[str, ImpactNode] = field(default_factory=dict)
    edges: list[ImpactEdge] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> ImpactGraph:
        return cls(
            nodes={k: ImpactNode(**v) for k, v in d.get("nodes", {}).items()},
            edges=[ImpactEdge(**e) for e in d.get("edges", [])],
        )
```

- [ ] 5.4 `core/schemaforge_core/db_snapshot.py` (full code):

```python
"""Deterministic schema snapshot via pg_catalog / information_schema."""
from __future__ import annotations

from psycopg import Connection
from psycopg.rows import dict_row

from .models import DBSnapshot, TableInfo

TABLES_SQL = """
SELECT table_name
FROM information_schema.tables
WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
ORDER BY table_name
"""

COLUMNS_SQL = """
SELECT table_name, column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_schema = 'public'
ORDER BY table_name, ordinal_position
"""

INDEXES_SQL = """
SELECT t.relname AS table_name,
       i.relname AS index_name,
       ix.indisunique AS is_unique,
       a.attname AS column_name,
       array_position(ix.indkey, a.attnum) AS col_pos
FROM pg_class t
JOIN pg_index ix ON t.oid = ix.indrelid
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
WHERE t.relnamespace = 'public'::regnamespace
  AND t.relkind = 'r'
ORDER BY t.relname, i.relname, col_pos
"""

FKS_SQL = """
SELECT tc.table_name, kcu.column_name,
       ccu.table_name AS ref_table, ccu.column_name AS ref_column,
       tc.constraint_name
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu
  ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage ccu
  ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'
"""

ROWCOUNTS_SQL = """
SELECT relname, reltuples::bigint AS row_count
FROM pg_class
WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'
"""


def connect(dsn: str) -> Connection:
    return Connection.connect(dsn, row_factory=dict_row)


def snapshot(conn: Connection) -> DBSnapshot:
    snap = DBSnapshot()
    for row in conn.execute(TABLES_SQL):
        snap.tables[row["table_name"]] = TableInfo(name=row["table_name"])
    for row in conn.execute(COLUMNS_SQL):
        t = snap.tables.get(row["table_name"])
        if t is None:
            continue
        t.columns.append(
            _column_from_row(row)
        )
    for row in conn.execute(INDEXES_SQL):
        t = snap.tables.get(row["table_name"])
        if t is None:
            continue
        idx = next((i for i in t.indexes if i.name == row["index_name"]), None)
        if idx is None:
            idx = _IndexRow(name=row["index_name"], unique=row["is_unique"])
            t.indexes.append(idx)
        idx.columns.append(row["column_name"])
    for row in conn.execute(FKS_SQL):
        t = snap.tables.get(row["table_name"])
        if t is None:
            continue
        t.foreign_keys.append(
            _FKRow(
                name=row["constraint_name"],
                column=row["column_name"],
                ref_table=row["ref_table"],
                ref_column=row["ref_column"],
            )
        )
    for row in conn.execute(ROWCOUNTS_SQL):
        t = snap.tables.get(row["relname"])
        if t:
            t.row_count = row["row_count"]
    return snap


def _column_from_row(row):
    from .models import ColumnInfo

    return ColumnInfo(
        name=row["column_name"],
        data_type=row["data_type"],
        nullable=row["is_nullable"] == "YES",
        default=row["column_default"],
    )


def _IndexRow(*, name, unique):
    from .models import IndexInfo

    return IndexInfo(name=name, columns=[], unique=unique)


def _FKRow(*, name, column, ref_table, ref_column):
    from .models import ForeignKeyInfo

    return ForeignKeyInfo(
        name=name, column=column, ref_table=ref_table, ref_column=ref_column
    )


def diff_tables(before: DBSnapshot, after: DBSnapshot) -> dict[str, list[str]]:
    """Structural diff: added/removed tables and added/removed columns."""
    added_tables = sorted(set(after.tables) - set(before.tables))
    removed_tables = sorted(set(before.tables) - set(after.tables))
    added_cols: list[str] = []
    removed_cols: list[str] = []
    for name, t in after.tables.items():
        b = before.tables.get(name)
        if b is None:
            continue
        bcols = {c.name for c in b.columns}
        acols = {c.name for c in t.columns}
        added_cols += [f"{name}.{c}" for c in sorted(acols - bcols)]
        removed_cols += [f"{name}.{c}" for c in sorted(bcols - acols)]
    return {
        "added_tables": added_tables,
        "removed_tables": removed_tables,
        "added_columns": added_cols,
        "removed_columns": removed_cols,
    }
```

- [ ] 5.5 TDD: `core/tests/__init__.py` (empty) and
  `core/tests/test_diff_tables.py`:

```python
from schemaforge_core.db_snapshot import diff_tables
from schemaforge_core.models import ColumnInfo, DBSnapshot, TableInfo


def _snap(tables: dict[str, list[tuple[str, str]]]) -> DBSnapshot:
    snap = DBSnapshot()
    for name, cols in tables.items():
        snap.tables[name] = TableInfo(
            name=name, columns=[ColumnInfo(name=c, data_type="varchar", nullable=False) for c in cols]
        )
    return snap


def test_diff_detects_split_shape():
    before = _snap({"users": ["id", "email", "address", "date_of_birth"]})
    after = _snap(
        {
            "users": ["id", "email"],
            "user_profiles": ["id", "user_id", "address", "date_of_birth"],
        }
    )
    d = diff_tables(before, after)
    assert d["added_tables"] == ["user_profiles"]
    assert d["removed_tables"] == []
    assert d["removed_columns"] == ["users.address", "users.date_of_birth"]
    assert d["added_columns"] == []
```

- [ ] 5.6 Install core editable + run the red test, then implement, then green:

```bash
cd /home/utsav/Github/schemaforge
uv pip install --python .vevn/bin/python -e core
.vevn/bin/pytest core/tests -q
# live check against dev DB:
.vevn/bin/python - <<'EOF'
import json
from schemaforge_core.db_snapshot import connect, snapshot
with connect("postgresql://postgres:postgres@localhost:5434/bookstore") as conn:
    snap = snapshot(conn)
print(json.dumps(snap.to_dict(), indent=2)[:800])
EOF
```

- [ ] 5.7 Branch `feat/core-snapshot`, PR #4 (include the live-check JSON in the
  PR description as evidence). Qodo → merge.

**Acceptance:** `test_diff_detects_split_shape` green; live snapshot shows
`users` (5 cols) + `books` with `reltuples` row counts.

## Task 6 — core: code_facts (PR #5)

Steps:
- [ ] 6.1 Write the RED tests first: `core/tests/test_code_facts.py`:

```python
from pathlib import Path

from schemaforge_core.code_facts import collect_facts, _tables_from_sql

DEMO = Path(__file__).resolve().parents[2] / "demo-app"


def test_extracts_models():
    facts = collect_facts(str(DEMO))
    user = next(m for m in facts.models if m.name == "User")
    assert user.table == "users"
    assert set(user.columns) == {"id", "name", "email", "address", "date_of_birth"}
    book = next(m for m in facts.models if m.name == "Book")
    assert book.table == "books"


def test_extracts_attr_accesses():
    facts = collect_facts(str(DEMO))
    cols = {(a.model, a.column) for a in facts.attr_accesses}
    assert ("User", "address") in cols
    assert ("User", "date_of_birth") in cols


def test_extracts_raw_sql_tables():
    facts = collect_facts(str(DEMO))
    assert any("users" in r.tables for r in facts.raw_sql)


def test_extracts_endpoints():
    facts = collect_facts(str(DEMO))
    paths = {(e.method, e.path) for e in facts.endpoints}
    assert ("GET", "/users") in paths
    assert ("GET", "/users/{user_id}") in paths
    assert ("GET", "/reports/addresses") in paths


def test_tables_from_sql():
    assert _tables_from_sql("SELECT u.name FROM users u WHERE u.id = 1") == ["users"]
    assert _tables_from_sql(
        "INSERT INTO user_profiles (user_id, address) SELECT id, address FROM users"
    ) == ["user_profiles", "users"]
    assert _tables_from_sql(
        "SELECT u.name, p.address FROM users u JOIN user_profiles p ON p.user_id = u.id"
    ) == ["users", "user_profiles"]
```

- [ ] 6.2 Implement `core/schemaforge_core/code_facts.py` (full code):

```python
"""Deterministic code facts from a Python source tree.

Pass 1 collects SQLAlchemy declarative models (class ↔ table ↔ columns).
Pass 2, with the model map known, collects FastAPI endpoints, attribute
accesses of known model columns on model-typed arguments, and raw-SQL table
references (via sqlparse). No LLM involved; outputs are stable JSON.
"""
from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import sqlparse
from sqlparse import tokens as T

from .models import AttrAccess, CodeFacts, EndpointFact, ModelFact, RawSqlRef

_ROUTE_METHODS = {"get", "post", "put", "patch", "delete"}
_TABLE_KEYWORDS = {"FROM", "JOIN", "INTO", "UPDATE", "TABLE"}


def _tables_from_sql(sql: str) -> list[str]:
    """Table names following FROM/JOIN/INTO/UPDATE/TABLE in a SQL string."""
    try:
        parsed = sqlparse.parse(sql)
    except Exception:
        return []
    if not parsed:
        return []
    found: list[str] = []
    for stmt in parsed:
        prev_keyword: ast.expr | None = None
        for tok in stmt.flatten():
            if tok.is_whitespace:
                continue
            if tok.ttype is T.Keyword or (
                tok.ttype is None and tok.value.upper() in _TABLE_KEYWORDS
            ):
                prev_keyword = tok
                continue
            if prev_keyword is not None:
                if tok.ttype is T.Name or tok.ttype is None:
                    v = tok.value.strip().strip('"').strip("`")
                    if v and not v.startswith("("):
                        found.append(v)
                    prev_keyword = None
                elif tok.ttype in (T.Punctuation, T.Operator):
                    prev_keyword = None
    seen: set[str] = set()
    out: list[str] = []
    for t in found:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _fid(path: str) -> str:
    return hashlib.md5(path.encode()).hexdigest()[:8]


def _model_names_in_annotation(ann: ast.expr, models: set[str]) -> list[str]:
    names: list[str] = []
    for n in ast.walk(ann):
        if isinstance(n, ast.Name) and n.id in models:
            names.append(n.id)
    return list(dict.fromkeys(names))


class _ModelPass(ast.NodeVisitor):
    """Pass 1: SQLAlchemy declarative models."""

    def __init__(self, path: Path):
        self.path = path
        self.models: list[ModelFact] = []
        self.columns_by_model: dict[str, list[str]] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        table: str | None = None
        columns: list[str] = []
        for stmt in node.body:
            if isinstance(stmt, ast.Assign):
                for t in stmt.targets:
                    if isinstance(t, ast.Name) and t.id == "__tablename__":
                        if (
                            isinstance(stmt.value, ast.Constant)
                            and isinstance(stmt.value.value, str)
                        ):
                            table = stmt.value.value
                if (
                    isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.value.func, ast.Name)
                    and stmt.value.func.id == "mapped_column"
                    and stmt.value.args
                    and isinstance(stmt.value.args[0], ast.Constant)
                    and isinstance(stmt.value.args[0].value, str)
                ):
                    for t in stmt.targets:
                        if isinstance(t, ast.Name):
                            columns.append(t.id)
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                if (
                    isinstance(stmt.value, ast.Call)
                    and isinstance(stmt.value.func, ast.Name)
                    and stmt.value.func.id == "mapped_column"
                    and stmt.value.args
                    and isinstance(stmt.value.args[0], ast.Constant)
                    and isinstance(stmt.value.args[0].value, str)
                ):
                    columns.append(stmt.target.id)
        if table:
            self.models.append(
                ModelFact(
                    name=node.name, table=table, columns=columns,
                    file=str(self.path), line=node.lineno,
                )
            )
            self.columns_by_model[node.name] = columns
        self.generic_visit(node)


class _BodyVisitor(ast.NodeVisitor):
    """Records attr accesses / raw SQL inside ONE function body.

    Skips nested FunctionDef/Lambda/ClassDef (handled separately by the main
    visitor) so arg-type maps don't leak across scopes.
    """

    def __init__(self, owner: "_FunctionPass", arg_models: dict[str, str]):
        self.owner = owner
        self.arg_models = arg_models

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        return

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if (
            isinstance(node.value, ast.Name)
            and node.value.id in self.arg_models
            and node.attr in self.owner.columns_by_model.get(self.arg_models[node.value.id], [])
        ):
            self.owner.attr_accesses.append(
                AttrAccess(
                    model=self.arg_models[node.value.id],
                    column=node.attr,
                    file=str(self.owner.path),
                    line=node.lineno,
                    function=self.owner.func_name,
                )
            )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        is_text = isinstance(node.func, ast.Name) and node.func.id == "text"
        is_execute = (
            isinstance(node.func, ast.Attribute) and node.func.attr == "execute"
        )
        if (is_text or is_execute) and node.args and isinstance(
            node.args[0], ast.Constant
        ) and isinstance(node.args[0].value, str):
            tables = _tables_from_sql(node.args[0].value)
            if tables:
                self.owner.raw_sql.append(
                    RawSqlRef(
                        tables=tables,
                        file=str(self.owner.path),
                        line=node.lineno,
                        function=self.owner.func_name,
                    )
                )
        self.generic_visit(node)


class _FunctionPass(ast.NodeVisitor):
    """Pass 2: endpoints, attr accesses, raw SQL (needs the model map)."""

    def __init__(self, path: Path, columns_by_model: dict[str, list[str]]):
        self.path = path
        self.columns_by_model = columns_by_model
        self.endpoints: list[EndpointFact] = []
        self.attr_accesses: list[AttrAccess] = []
        self.raw_sql: list[RawSqlRef] = []
        self.func_name: str | None = None

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._handle_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._handle_function(node)

    def _handle_function(self, node) -> None:
        outer = self.func_name
        self.func_name = node.name

        for dec in node.decorator_list:
            if (
                isinstance(dec, ast.Call)
                and isinstance(dec.func, ast.Attribute)
                and dec.func.attr in _ROUTE_METHODS
                and dec.args
                and isinstance(dec.args[0], ast.Constant)
                and isinstance(dec.args[0].value, str)
            ):
                self.endpoints.append(
                    EndpointFact(
                        path=dec.args[0].value,
                        method=dec.func.attr.upper(),
                        file=str(self.path),
                        line=node.lineno,
                        function=node.name,
                    )
                )

        arg_models: dict[str, str] = {}
        for a in list(node.args.posonlyargs) + list(node.args.args):
            if a.annotation is not None:
                names = _model_names_in_annotation(
                    a.annotation, set(self.columns_by_model)
                )
                if len(names) == 1:
                    arg_models[a.arg] = names[0]

        _BodyVisitor(self, arg_models).visit(node.body)

        for dec in node.decorator_list:
            self.visit(dec)
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(stmt)

        self.func_name = outer


def collect_facts(app_dir: str) -> CodeFacts:
    root = Path(app_dir)
    facts = CodeFacts()
    columns_by_model: dict[str, list[str]] = {}
    py_files = sorted(p for p in root.rglob("*.py") if "tests" not in p.parts)
    for f in py_files:
        try:
            tree = ast.parse(f.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        mp = _ModelPass(f)
        mp.visit(tree)
        facts.models.extend(mp.models)
        columns_by_model.update(mp.columns_by_model)
    for f in py_files:
        try:
            tree = ast.parse(f.read_text())
        except (SyntaxError, UnicodeDecodeError):
            continue
        fp = _FunctionPass(f, columns_by_model)
        fp.visit(tree)
        facts.endpoints.extend(fp.endpoints)
        facts.attr_accesses.extend(fp.attr_accesses)
        facts.raw_sql.extend(fp.raw_sql)
    return facts
```

- [ ] 6.3 `uv pip install --python .vevn/bin/python -e core` (re-run if already
  installed — no-op) and run:

```bash
cd /home/utsav/Github/schemaforge
.vevn/bin/pytest core/tests -q
```

  Iterate until all of Task 5 + Task 6 tests pass. Note: `collect_facts`
  excludes `tests/` dirs (test fixtures shouldn't pollute the graph).

- [ ] 6.4 Branch `feat/core-code-facts`, PR #5: description explains the
  two-pass design and the deliberate limits (attribute detection requires
  model-typed arguments; nested lambdas skipped). Qodo → merge.

**Acceptance:** all 5 code_facts tests + the diff test green against the real
demo-app tree.

## Task 7 — core: impact_graph + report + pipeline CLI (PR #6)

Steps:
- [ ] 7.1 `core/schemaforge_core/impact_graph.py` (full code):

```python
"""Impact graph: merge DB snapshot + code facts into a semantic graph and
project the blast radius of a schema change."""
from __future__ import annotations

from collections import defaultdict

from .models import CodeFacts, DBSnapshot, ImpactEdge, ImpactGraph, ImpactNode


def _mid(s: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in s).strip("_") or "x"


def build(snapshot: DBSnapshot, facts: CodeFacts) -> ImpactGraph:
    g = ImpactGraph(nodes={}, edges=[])

    for table in snapshot.tables.values():
        tid = f"table_{_mid(table.name)}"
        g.nodes[tid] = ImpactNode(id=tid, kind="table", label=table.name)
        for col in table.columns:
            cid = f"col_{_mid(table.name)}_{_mid(col.name)}"
            g.nodes[cid] = ImpactNode(
                id=cid, kind="column", label=f"{table.name}.{col.name}"
            )
            g.edges.append(ImpactEdge(src=tid, dst=cid, kind="has_column"))

    for m in facts.models:
        mid = f"model_{_mid(m.name)}"
        g.nodes[mid] = ImpactNode(id=mid, kind="model", label=m.name, file=m.file)
        tid = f"table_{_mid(m.table)}"
        if tid in g.nodes:
            g.edges.append(ImpactEdge(src=mid, dst=tid, kind="maps_to"))
        for c in m.columns:
            cid = f"col_{_mid(m.table)}_{_mid(c)}"
            if cid in g.nodes:
                g.edges.append(ImpactEdge(src=mid, dst=cid, kind="defines_column"))

    for a in facts.attr_accesses:
        aid = f"attr_{_mid(a.model)}_{_mid(a.column)}_{a.line}"
        g.nodes[aid] = ImpactNode(
            id=aid, kind="attr", label=f"{a.model}.{a.column}", file=a.file
        )
        mid = f"model_{_mid(a.model)}"
        if mid in g.nodes:
            g.edges.append(ImpactEdge(src=mid, dst=aid, kind="accessed_via"))

    for r in facts.raw_sql:
        rid = f"sql_{r.file.replace('/', '_').replace('.', '_')}_{r.line}"
        g.nodes[rid] = ImpactNode(
            id=rid, kind="rawsql", label=f"raw SQL @ {r.file}:{r.line}", file=r.file
        )
        for t in r.tables:
            tid = f"table_{_mid(t)}"
            if tid in g.nodes:
                g.edges.append(ImpactEdge(src=rid, dst=tid, kind="queries"))

    for e in facts.endpoints:
        eid = f"endpoint_{_mid(e.method)}_{_mid(e.path)}_{e.line}"
        g.nodes[eid] = ImpactNode(
            id=eid, kind="endpoint", label=f"{e.method} {e.path}", file=e.file
        )
        for a in facts.attr_accesses:
            if a.file == e.file and a.function == e.function:
                aid = f"attr_{_mid(a.model)}_{_mid(a.column)}_{a.line}"
                if aid in g.nodes:
                    g.edges.append(ImpactEdge(src=eid, dst=aid, kind="executes"))
        for r in facts.raw_sql:
            if r.file == e.file and r.function == e.function:
                rid = f"sql_{r.file.replace('/', '_').replace('.', '_')}_{r.line}"
                if rid in g.nodes:
                    g.edges.append(ImpactEdge(src=eid, dst=rid, kind="executes"))

    return g


def impacted_by(g: ImpactGraph, tables: list[str]) -> dict:
    """Reverse reachability from the given table nodes.

    Returns {files, endpoints, models, columns} affected by changing those tables.
    """
    start = {f"table_{_mid(t)}" for t in tables}
    rev: dict[str, list[str]] = defaultdict(list)
    for e in g.edges:
        rev[e.dst].append(e.src)

    seen: set[str] = set()
    stack = [n for n in start if n in g.nodes]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        stack.extend(rev.get(n, []))

    files: set[str] = set()
    endpoints: list[str] = []
    models: list[str] = []
    columns: list[str] = []
    for nid in seen:
        node = g.nodes[nid]
        if node.kind == "model":
            models.append(node.label)
        elif node.kind == "column":
            columns.append(node.label)
        elif node.kind == "endpoint":
            endpoints.append(node.label)
        if node.file:
            files.add(node.file)
    return {
        "files": sorted(files),
        "endpoints": sorted(endpoints),
        "models": sorted(models),
        "columns": sorted(columns),
    }


def to_mermaid(g: ImpactGraph) -> str:
    lines = ["flowchart LR"]
    by_kind: dict[str, list[ImpactNode]] = defaultdict(list)
    for n in g.nodes.values():
        by_kind[n.kind].append(n)
    for kind in ("table", "column", "model", "attr", "rawsql", "endpoint"):
        nodes = by_kind.get(kind)
        if not nodes:
            continue
        lines.append(f"    subgraph {kind}")
        for n in sorted(nodes, key=lambda x: x.id):
            lines.append(f"        {n.id}[\"{n.label}\"]")
        lines.append("    end")
    for e in g.edges:
        lines.append(f"    {e.src} -->|{e.kind}| {e.dst}")
    return "\n".join(lines)
```

- [ ] 7.2 `core/schemaforge_core/report.py` (full code):

```python
"""Safety report rendering (markdown, for chat display + PR body)."""
from __future__ import annotations

import datetime as _dt


def render_report(r: dict) -> str:
    lines = ["# SchemaForge Safety Report", ""]
    lines.append(f"Generated: {_dt.datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append("## Verification")
    lines.append(f"- Alembic migration: {'PASS' if r['alembic_ok'] else 'FAIL'}")
    lines.append(f"- Application tests: {'PASS' if r['pytest_ok'] else 'FAIL'}")
    if r.get("parity_ok") is not None:
        lines.append(f"- Data parity: {'PASS' if r['parity_ok'] else 'FAIL'}")
    lines.append("")
    lines.append("## Schema diff")
    d = r.get("diff", {})
    for key in ("added_tables", "removed_tables", "added_columns", "removed_columns"):
        items = d.get(key, [])
        lines.append(f"- {key.replace('_', ' ')}: {', '.join(items) if items else '(none)'}")
    lines.append("")
    lines.append("## Query performance (sandbox, EXPLAIN ANALYZE, wall ms)")
    for e in r.get("explain", []):
        before = f"{e['ms_before']} ms" if e.get("ms_before") is not None else "n/a"
        lines.append(f"- `{e['query']}`: before = {before}, after = {e['ms']} ms")
    lines.append("")
    lines.append("## Rollback")
    lines.append("`alembic downgrade -1` restores the previous schema "
                 "(the revision ships its own `downgrade()`).")
    lines.append("")
    lines.append("## Approval checklist")
    lines.append("- [ ] Impact graph reviewed")
    lines.append("- [ ] Schema diff reviewed")
    lines.append("- [ ] Sandbox tests + parity green")
    lines.append("- [ ] Query plans acceptable")
    lines.append("- [ ] Approve `execute_ddl` on production? (answer in chat)")
    return "\n".join(lines) + "\n"
```

- [ ] 7.3 `core/schemaforge_core/pipeline.py` (full code):

```python
"""SchemaForge deterministic pipeline CLI.

Commands:
  snapshot  --dsn URL --out out/db.json
  facts     --app demo-app --out out/code.json
  graph     --db out/db.json --code out/code.json --out out/graph.json --mermaid out/graph.mmd
  verify    --dir demo-app --dsn URL --baseline out/db_before.json
            [--parity-sql reference/post-split/parity.sql]
            [--queries demo-app/queries/bench.sql]
            [--explain-before out/explain_before.json]
            --out out/report.md
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .code_facts import collect_facts
from .db_snapshot import connect, diff_tables, snapshot
from .impact_graph import build, impacted_by, to_mermaid
from .models import CodeFacts, DBSnapshot
from .report import render_report


def cmd_snapshot(args: argparse.Namespace) -> None:
    with connect(args.dsn) as conn:
        snap = snapshot(conn)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(snap.to_dict(), indent=2))
    print(f"snapshot -> {args.out} ({len(snap.tables)} tables)")


def cmd_facts(args: argparse.Namespace) -> None:
    facts = collect_facts(args.app)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(facts.to_dict(), indent=2))
    print(
        f"facts -> {args.out} ({len(facts.models)} models, "
        f"{len(facts.endpoints)} endpoints, {len(facts.attr_accesses)} attr accesses, "
        f"{len(facts.raw_sql)} raw-sql refs)"
    )


def cmd_graph(args: argparse.Namespace) -> None:
    snap = DBSnapshot.from_dict(json.loads(Path(args.db).read_text()))
    facts = CodeFacts.from_dict(json.loads(Path(args.code).read_text()))
    g = build(snap, facts)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(g.to_dict(), indent=2))
    if args.mermaid:
        Path(args.mermaid).write_text(to_mermaid(g))
        print(f"graph -> {out} + {args.mermaid} ({len(g.nodes)} nodes, {len(g.edges)} edges)")
    else:
        print(f"graph -> {out} ({len(g.nodes)} nodes, {len(g.edges)} edges)")


def cmd_impact(args: argparse.Namespace) -> None:
    g = _load_graph(args.db, args.code)
    hit = impacted_by(g, [t.strip() for t in args.tables.split(",") if t.strip()])
    out = Path(args.out) if args.out else None
    text = json.dumps(hit, indent=2)
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    print(text)


def _load_graph(db_path: str, code_path: str):
    snap = DBSnapshot.from_dict(json.loads(Path(db_path).read_text()))
    facts = CodeFacts.from_dict(json.loads(Path(code_path).read_text()))
    return build(snap, facts)


def _run(cmd: list[str], cwd: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=900)


def cmd_verify(args: argparse.Namespace) -> None:
    env = {**os.environ, "DATABASE_URL": args.dsn}
    dir_ = Path(args.dir)

    alembic = _run(["alembic", "upgrade", "head"], dir_, env)

    with connect(args.dsn) as conn:
        after = snapshot(conn)
        before = DBSnapshot.from_dict(json.loads(Path(args.baseline).read_text()))
        diff = diff_tables(before, after)
        parity_ok: bool | None = None
        parity_out = ""
        if args.parity_sql:
            sql = Path(args.parity_sql).read_text()
            rows = conn.execute(sql).fetchall()
            parity_out = "\n".join(json.dumps(dict(r), default=str) for r in rows)
            parity_ok = all(
                bool(v)
                for r in rows
                for v in r.values()
                if isinstance(v, bool)
            )

    pytest = _run(["pytest", "-q"], dir_, env)

    before_explain: dict[str, float] = {}
    if args.explain_before and Path(args.explain_before).exists():
        before_explain = json.loads(Path(args.explain_before).read_text())
    explain: list[dict] = []
    for name, sql in _load_queries(Path(args.queries)):
        with connect(args.dsn) as conn:
            t0 = time.perf_counter()
            conn.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}")
            ms = (time.perf_counter() - t0) * 1000
        explain.append(
            {"query": name, "ms": round(ms, 1), "ms_before": before_explain.get(name)}
        )

    result = {
        "alembic_ok": alembic.returncode == 0,
        "alembic_output": (alembic.stdout + alembic.stderr)[-2000:],
        "pytest_ok": pytest.returncode == 0,
        "pytest_output": (pytest.stdout + pytest.stderr)[-3000:],
        "parity_ok": parity_ok,
        "parity_output": parity_out[-2000:],
        "diff": diff,
        "explain": explain,
    }
    report = render_report(result)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(report)
    sys.exit(
        0 if (result["alembic_ok"] and result["pytest_ok"] and parity_ok is not False) else 1
    )


def cmd_bench(args: argparse.Namespace) -> None:
    """Record EXPLAIN ANALYZE timings (pre-migration baseline)."""
    timings: dict[str, float] = {}
    with connect(args.dsn) as conn:
        for name, sql in _load_queries(Path(args.queries)):
            t0 = time.perf_counter()
            conn.execute(f"EXPLAIN (ANALYZE, BUFFERS) {sql}")
            timings[name] = round((time.perf_counter() - t0) * 1000, 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(timings, indent=2))
    print(json.dumps(timings, indent=2))


def _load_queries(path: Path) -> list[tuple[str, str]]:
    queries: list[tuple[str, str]] = []
    current: str | None = None
    buf: list[str] = []
    for line in path.read_text().splitlines():
        if line.startswith("-- name:"):
            if current:
                queries.append((current, "\n".join(buf).strip()))
            current = line.split(":", 1)[1].strip()
            buf = []
        else:
            buf.append(line)
    if current:
        queries.append((current, "\n".join(buf).strip()))
    return queries


def main() -> None:
    p = argparse.ArgumentParser(prog="schemaforge_core")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("snapshot")
    s.add_argument("--dsn", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_snapshot)

    s = sub.add_parser("facts")
    s.add_argument("--app", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_facts)

    s = sub.add_parser("graph")
    s.add_argument("--db", required=True)
    s.add_argument("--code", required=True)
    s.add_argument("--out", required=True)
    s.add_argument("--mermaid")
    s.set_defaults(fn=cmd_graph)

    s = sub.add_parser("impact")
    s.add_argument("--db", required=True)
    s.add_argument("--code", required=True)
    s.add_argument("--tables", required=True, help="comma-separated table names")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_impact)

    s = sub.add_parser("verify")
    s.add_argument("--dir", required=True)
    s.add_argument("--dsn", required=True)
    s.add_argument("--baseline", required=True)
    s.add_argument("--parity-sql")
    s.add_argument("--queries", required=True)
    s.add_argument("--explain-before")
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("bench")
    s.add_argument("--dsn", required=True)
    s.add_argument("--queries", required=True)
    s.add_argument("--out", required=True)
    s.set_defaults(fn=cmd_bench)

    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
```

- [ ] 7.4 `core/schemaforge_core/__main__.py`:

```python
from .pipeline import main

if __name__ == "__main__":
    main()
```

- [ ] 7.5 RED tests first: `core/tests/test_impact_graph.py`:

```python
from schemaforge_core.impact_graph import build, impacted_by, to_mermaid
from schemaforge_core.models import (
    AttrAccess,
    CodeFacts,
    ColumnInfo,
    DBSnapshot,
    EndpointFact,
    ModelFact,
    RawSqlRef,
    TableInfo,
)


def _fixture():
    snap = DBSnapshot()
    snap.tables["users"] = TableInfo(
        name="users",
        columns=[
            ColumnInfo(name="id", data_type="integer", nullable=False),
            ColumnInfo(name="email", data_type="varchar", nullable=False),
            ColumnInfo(name="address", data_type="varchar", nullable=False),
        ],
    )
    facts = CodeFacts(
        models=[
            ModelFact(name="User", table="users",
                      columns=["id", "email", "address"],
                      file="app/models.py", line=5)
        ],
        attr_accesses=[
            AttrAccess(model="User", column="address",
                       file="app/routers/users.py", line=10, function="list_users"),
            AttrAccess(model="User", column="email",
                       file="app/routers/users.py", line=12, function="get_user"),
        ],
        raw_sql=[
            RawSqlRef(tables=["users"], file="app/routers/reports.py",
                      line=5, function="user_addresses")
        ],
        endpoints=[
            EndpointFact(path="/users", method="GET", file="app/routers/users.py",
                         line=8, function="list_users"),
            EndpointFact(path="/users/{user_id}", method="GET",
                         file="app/routers/users.py", line=20, function="get_user"),
            EndpointFact(path="/reports/addresses", method="GET",
                         file="app/routers/reports.py", line=4, function="user_addresses"),
        ],
    )
    return snap, facts


def test_build_has_expected_edge_kinds():
    snap, facts = _fixture()
    g = build(snap, facts)
    kinds = {e.kind for e in g.edges}
    assert {"maps_to", "has_column", "accessed_via", "queries", "executes"} <= kinds


def test_impacted_by_users_covers_all_code_paths():
    snap, facts = _fixture()
    g = build(snap, facts)
    hit = impacted_by(g, ["users"])
    assert "app/models.py" in hit["files"]
    assert "app/routers/users.py" in hit["files"]
    assert "app/routers/reports.py" in hit["files"]
    assert "GET /users" in hit["endpoints"]
    assert "GET /reports/addresses" in hit["endpoints"]
    assert "User" in hit["models"]
    assert "users.address" in hit["columns"]


def test_impacted_by_unknown_table_is_empty():
    snap, facts = _fixture()
    g = build(snap, facts)
    hit = impacted_by(g, ["nonexistent"])
    assert hit["files"] == []
    assert hit["endpoints"] == []


def test_mermaid_renders_subgraphs():
    snap, facts = _fixture()
    g = build(snap, facts)
    mmd = to_mermaid(g)
    assert mmd.startswith("flowchart LR")
    assert "subgraph table" in mmd
    assert "subgraph endpoint" in mmd
    assert 'label' not in mmd  # sanity: no leaked python reprs
```

  and `core/tests/test_queries_parser.py`:

```python
from pathlib import Path

from schemaforge_core.pipeline import _load_queries


def test_load_queries(tmp_path: Path):
    f = tmp_path / "bench.sql"
    f.write_text(
        "-- name: a\nSELECT 1;\n\n-- name: b\nSELECT 2;\n"
    )
    q = _load_queries(f)
    assert q == [("a", "SELECT 1;"), ("b", "SELECT 2;")]
```

- [ ] 7.6 Run until green: `.vevn/bin/pytest core/tests -q` (all of Tasks 5–7).
- [ ] 7.7 End-to-end CLI run against the dev DB:

```bash
cd /home/utsav/Github/schemaforge
DEV=postgresql://postgres:postgres@localhost:5434/bookstore
.vevn/bin/python -m schemaforge_core.pipeline snapshot --dsn "$DEV" --out out/db.json
.vevn/bin/python -m schemaforge_core.pipeline facts --app demo-app --out out/code.json
.vevn/bin/python -m schemaforge_core.pipeline graph --db out/db.json --code out/code.json --out out/graph.json --mermaid out/graph.mmd
.vevn/bin/python -m schemaforge_core.pipeline impact --db out/db.json --code out/code.json --tables users
.vevn/bin/python -m schemaforge_core.pipeline bench --dsn "$DEV" --queries demo-app/queries/bench.sql --out out/explain_before.json
cat out/graph.mmd
```

- [ ] 7.8 Branch `feat/core-graph-pipeline`, PR #6 (attach `out/graph.mmd` and the
  `impact` JSON in the PR description as evidence). Qodo → merge.

**Acceptance:** all core tests green; `impact --tables users` lists all three
app files and all three user-facing endpoints; mermaid file renders in
mermaid.live.

> Extension over the draft (implemented on Day 1): `code_facts` also records
> intra-file function calls as `FunctionCall` facts, and `impact_graph` links
> each endpoint to the attr/raw-SQL facts of every function it calls
> transitively in the same file (e.g. `to_out(user: User)`). Without this the
> demo-app's real attr accesses — all inside `to_out` — never connected to
> `GET /users`, so `impact --tables users` missed endpoints. `impacted_by`
> traverses the graph both ways (blast radius of changing a table includes
> everything depending on it and everything it contains).

---

# Day 2 — Aug 28 · Golden path + sandbox pipeline (Docker + Daytona CLI)

## Task 8 — Golden post-split reference + parity (PR #7)

**Goal:** hand-author the known-good outcome (the thing the agent should
reproduce autonomously) and prove the whole deterministic pipeline on it,
locally, before trusting it in the sandbox.

Steps:
- [ ] 8.1 `reference/post-split/README.md`:

```markdown
# Golden post-split outcome (reference only)

The expected result of the `users -> users + user_profiles` split. NOT wired
into `demo-app/` — the agent authors its own migration at runtime. This
reference is used to (a) sanity-check the agent's output and (b) prove the
deterministic pipeline end-to-end.

| File | What it is |
|---|---|
| alembic/versions/0002_split_users.py | data-preserving expand/backfill/contract migration |
| app/models.py | post-split ORM models |
| app/routers/users.py | join-based API (response shape unchanged) |
| tests/conftest.py | post-split test seed (User + UserProfile pairs) |
| queries/bench.sql | post-split EXPLAIN ANALYZE queries (joined reports query) |
| parity.sql | data-preservation assertions run by `pipeline verify` |
| parity.sql | data-preservation assertions run by `pipeline verify` |
```

- [ ] 8.2 `reference/post-split/alembic/versions/0002_split_users.py` (full code):

```python
"""split users into users + user_profiles (1:1)

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-28

Strategy: expand (create table) -> backfill (INSERT ... SELECT) -> contract
(drop moved columns). No window where a write to users can lose data; the
only lock moment is the final column drops (ACCESS EXCLUSIVE, brief).
"""
from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("address", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.String(length=10), nullable=True),
    )
    op.execute(
        "INSERT INTO user_profiles (user_id, address, date_of_birth) "
        "SELECT id, address, date_of_birth FROM users"
    )
    op.drop_column("users", "date_of_birth")
    op.drop_column("users", "address")


def downgrade() -> None:
    op.add_column("users", sa.Column("address", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("date_of_birth", sa.String(length=10), nullable=True))
    op.execute(
        "UPDATE users u SET address = p.address, date_of_birth = p.date_of_birth "
        "FROM user_profiles p WHERE p.user_id = u.id"
    )
    op.alter_column("users", "address", nullable=False)
    op.drop_table("user_profiles")
```

- [ ] 8.3 `reference/post-split/app/models.py`:

```python
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True)


class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True)
    address: Mapped[str] = mapped_column(String(255))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)


class Book(Base):
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(100))
    price_cents: Mapped[int] = mapped_column()
```

- [ ] 8.4 `reference/post-split/app/routers/users.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import SessionLocal
from ..models import User, UserProfile

router = APIRouter(prefix="/users", tags=["users"])


class UserIn(BaseModel):
    name: str
    email: str
    address: str
    date_of_birth: str | None = None


class UserOut(BaseModel):
    id: int
    name: str
    email: str
    address: str
    date_of_birth: str | None


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def to_out(user: User, profile: UserProfile) -> UserOut:
    return UserOut(
        id=user.id,
        name=user.name,
        email=user.email,
        address=profile.address,
        date_of_birth=profile.date_of_birth,
    )


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db)):
    pairs = (
        db.query(User, UserProfile)
        .join(UserProfile, UserProfile.user_id == User.id)
        .order_by(User.id)
        .all()
    )
    return [to_out(u, p) for u, p in pairs]


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    pair = (
        db.query(User, UserProfile)
        .join(UserProfile, UserProfile.user_id == User.id)
        .filter(User.id == user_id)
        .one_or_none()
    )
    if pair is None:
        raise HTTPException(status_code=404, detail="user not found")
    user, profile = pair
    return to_out(user, profile)


@router.post("", response_model=UserOut, status_code=201)
def create_user(payload: UserIn, db: Session = Depends(get_db)):
    user = User(name=payload.name, email=payload.email)
    profile = UserProfile(
        user_id=0,
        address=payload.address,
        date_of_birth=payload.date_of_birth,
    )
    db.add(user)
    db.flush()
    profile.user_id = user.id
    db.add(profile)
    db.commit()
    db.refresh(user)
    db.refresh(profile)
    return to_out(user, profile)
```

- [ ] 8.5 `reference/post-split/app/routers/reports.py`:

```python
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from ..db import SessionLocal

router = APIRouter(prefix="/reports", tags=["reports"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/addresses")
def user_addresses(db: Session = Depends(get_db)):
    rows = db.execute(
        text(
            "SELECT u.name, p.address FROM users u "
            "JOIN user_profiles p ON p.user_id = u.id "
            "ORDER BY u.id LIMIT 20"
        )
    ).fetchall()
    return [{"name": r.name, "address": r.address} for r in rows]
```

- [ ] 8.6 `reference/post-split/parity.sql`:

```sql
-- Data-preservation assertions for the users -> users + user_profiles split.
-- Run AFTER the migration; every boolean column must be true.
SELECT
    (SELECT count(*) FROM users) = (SELECT count(*) FROM user_profiles)
        AS profiles_complete,
    (SELECT count(*) FROM user_profiles WHERE address IS NULL) = 0
        AS no_null_addresses,
    (SELECT count(*) FROM users u LEFT JOIN user_profiles p ON p.user_id = u.id
       WHERE p.id IS NULL) = 0
        AS all_users_have_profiles;
```

- [ ] 8.7 Prove the golden path locally (this exact sequence is what the
  sandbox will run; keep the commands in your notes for the video):

```bash
cd /home/utsav/Github/schemaforge
DEV=postgresql://postgres:postgres@localhost:5434/bookstore
# fresh state
docker compose -f demo-app/docker-compose.dev.yml down -v && docker compose -f demo-app/docker-compose.dev.yml up -d
sleep 3
(cd demo-app && DATABASE_URL="$DEV" ../.vevn/bin/alembic upgrade head && DATABASE_URL="$DEV" ../.vevn/bin/python seed.py 100000 1000)
# pre-migration baseline
.vevn/bin/python -m schemaforge_core.pipeline snapshot --dsn "$DEV" --out out/db_before.json
.vevn/bin/python -m schemaforge_core.pipeline facts --app demo-app --out out/code.json
.vevn/bin/python -m schemaforge_core.pipeline bench --dsn "$DEV" --queries demo-app/queries/bench.sql --out out/explain_before.json
# apply the golden outcome (copy files into the app tree)
cp reference/post-split/alembic/versions/0002_split_users.py demo-app/alembic/versions/
cp reference/post-split/app/models.py demo-app/app/models.py
cp reference/post-split/tests/conftest.py demo-app/tests/conftest.py
cp reference/post-split/queries/bench.sql demo-app/queries/bench.sql
# verify
# verify
.vevn/bin/python -m schemaforge_core.pipeline verify \
  --dir demo-app --dsn "$DEV" --baseline out/db_before.json \
  --parity-sql reference/post-split/parity.sql \
  --queries demo-app/queries/bench.sql \
  --explain-before out/explain_before.json \
  --out out/report_golden.md
# expect: exit 0, report shows PASS/PASS/PASS
# then restore main state:
git checkout -- demo-app/ && rm demo-app/alembic/versions/0002_split_users.py
```

- [ ] 8.8 Branch `feat/golden-reference`, PR #7 (attach `out/report_golden.md`
  in the description). Qodo → merge.

> **Day-2 deviations (2026-08-26, proven live):** the draft's reference tree and
> copy list were missing two files that `verify` needs against post-split code —
> `tests/conftest.py` (the pre-split seed constructs `User(address=...)`, which
> TypeErrors post-split) and `queries/bench.sql` (the pre-split `addresses_report`
> reads `u.address`, which no longer exists). Both now ship in
> `reference/post-split/` and are copied in 8.7. `pipeline verify` also had a
> robustness bug: it shelled out to `alembic`/`pytest` by bare name, which fails
> when the venv bin is not on PATH (`.vevn/bin/python` direct invocation, or
> sandbox agents with a minimal environment); fixed via `_tool()` resolving the
> console scripts next to `sys.executable` (symlink-aware, no `.resolve()`).
> Golden-path run against a 100k-user dev DB: verify EXIT=0, all three PASS
> lines, parity all true, and `alembic downgrade 0001` restored 100k users with
> 0 null addresses / 50k null dobs — byte-identical to the seed source.

## Task 9 — Sandbox rehearsal: Docker (script logic) + Daytona CLI (real env) (no PR — ops validation)

**Goal:** validate `sandbox_setup.sh` + the pipeline in two layers — Docker
for fast script-logic iteration, then the REAL Daytona platform via the
Daytona CLI (API key from `~/.zshrc`) — so Day 3's live run has no
environment surprises.

Steps:
- [ ] 9.1 `scripts/sandbox_setup.sh` (full code — this is what the AGENT runs
  inside the Daytona sandbox after `git clone`):

```bash
#!/usr/bin/env bash
# Run INSIDE the TrueForge sandbox against the repo checkout at /workspace.
# Sets up: postgres in-sandbox, python deps, baseline schema + 100k seed.
set -euxo pipefail

PG_VER=$(ls /etc/postgresql | sort -V | tail -1)

if ! command -v psql >/dev/null; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq postgresql postgresql-contrib python3-pip
fi
service postgresql start || pg_ctlcluster "$PG_VER" main start
su postgres -c "psql -c \"ALTER USER postgres PASSWORD 'postgres'\"" || true
su postgres -c "createdb bookstore" || true

cd /workspace
python3 -m pip install --quiet -e core -r demo-app/requirements.txt

export DATABASE_URL=postgresql://postgres:postgres@localhost:5432/bookstore
(cd demo-app && alembic upgrade head)
(cd demo-app && python seed.py 100000 1000)

echo "SANDBOX_READY"
```

- [ ] 9.2 Rehearse in Docker. This validates the **script logic only** —
  the real Daytona platform is exercised in 9.5 (CLI), and the harness's
  own provisioning path in 11.7 (Day 3). Use the uv image below:

```bash
docker run --rm -it -v /home/utsav/Github/schemaforge:/workspace -w /workspace \
  -e PYTHONPATH=/workspace/core \
  ghcr.io/astral-sh/uv:python3.14-bookworm-slim bash scripts/sandbox_setup.sh
```

  (If that image name isn't pullable, use `python:3.12-bookworm` and `uv
  venv`-style installs; the point is to validate `sandbox_setup.sh` logic,
  not the exact base image. Daytona's default image already has python.)

- [ ] 9.3 Inside the same container session, run the full Day-2 golden
  sequence (8.7 commands, with `DEV=postgresql://postgres:postgres@localhost:5432/bookstore`
  and `uv run --project core python -m schemaforge_core.pipeline ...` or the
  container's python). Record: total wall time, any failure mode, the exact
  report content.
- [ ] 9.4 If anything in `sandbox_setup.sh` or `pipeline verify` breaks, fix it
  on a `fix/sandbox-rehearsal` branch and roll the fixes into PR #7 (amend the
  open PR before merge) or open PR #7b.
- [ ] 9.5 **Daytona CLI rehearsal — the real platform** (Docker only proved
  the script logic; this proves Daytona itself, a day before we need it).
  CLI syntax verified against the official docs (daytona.io/docs/en/tools/cli):

```bash
# one-time install (Linux x86_64)
sudo curl -fL https://github.com/daytonaio/daytona/releases/latest/download/daytona-linux-amd64 \
  -o /usr/local/bin/daytona && sudo chmod +x /usr/local/bin/daytona

# $DAYTONA_API_KEY is exported in ~/.zshrc (interactive shell)
daytona login --api-key "$DAYTONA_API_KEY"
daytona create --name sf-rehearsal        # default snapshot/region; ~seconds to provision
daytona list

# network + python sanity (this answers the apt/network unknowns)
daytona exec sf-rehearsal -- timeout 60 bash -lc 'curl -sI https://github.com | head -1; python3 --version; id'

# repo, same path the harness /workspace is expected to provide
daytona exec sf-rehearsal -- bash -lc 'git clone --depth 1 https://github.com/<you>/schemaforge /workspace'

# the full setup (longest command — give it room)
daytona exec sf-rehearsal --timeout 1800 -- bash -lc 'cd /workspace && bash scripts/sandbox_setup.sh'

# engine smoke inside the sandbox
daytona exec sf-rehearsal --timeout 300 -- bash -lc 'cd /workspace && python3 -m schemaforge_core.pipeline snapshot --dsn postgresql://postgres:postgres@localhost:5432/bookstore --out out/db.json && python3 -c "import json;print(len(json.load(open(\"out/db.json\"))[\"tables\"]))"'   # expect: 2

# teardown (do not leave sandboxes running — they bill)
daytona delete sf-rehearsal

  (If the nested-quoting one-liner above fights you, `daytona ssh sf-rehearsal`
  gives a real shell — same thing, easier typing.)

  **Record:** provisioning time (create → first exec), apt availability,
  whether `SANDBOX_READY` printed, the table count (expect 2), total wall
  time. If Daytona's base image differs from the Docker rehearsal (no apt,
  different python, no root), fix `sandbox_setup.sh` and re-run 9.5 — that
  is exactly the failure mode this step exists to catch.

> **Day-2 rehearsal findings (2026-08-26, both layers proven):** the real
> Daytona default image is **Debian 13 trixie, non-root `daytona` user (uid
> 1001) with passwordless sudo, PEP 668 externally-managed python 3.14** —
> three realities the draft script missed. `sandbox_setup.sh` now: sudo-prefixes
> apt/service/postgres when not root (`run_postgres`: `su` as root, `sudo -u`
> otherwise), installs when the postgres *server* is missing (not just psql),
> and creates a venv at `$HOME/.sfenv` (bare pip is refused on PEP 668
> systems; venv keeps alembic/pytest/pipeline on one PATH). It writes
> `/workspace/.sfenv-activate.sh` — later shells (and the Day-3 agent) must
> `source` it. Measured: Daytona create→ready ≈ 2s, setup (apt postgres 17 +
> venv deps + alembic 0001 + 100k seed) ≈ 33s; snapshot lists **3 tables**
> (`alembic_version`, `books`, `users`) — the draft's "2 tables" meant the two
> domain tables. Docker (root) full golden sequence: all PASS; Daytona:
> `SANDBOX_READY` + 3 tables.

## Task 10 — TrueForge connector + skill registration (no PR — config)

Steps:
- [ ] 10.1 Start the MCP servers: `bash scripts/run_mcp_servers.sh` (keep running
  in a terminal / tmux).
- [ ] 10.2 In TrueForge UI → Settings → Connectors: add `postgres-prod`
  (url `http://localhost:8001/mcp`, no auth) and `github`
  (url `http://localhost:8002/mcp`; if the server requires it, header auth
  `Authorization: Bearer $GITHUB_PERSONAL_ACCESS_TOKEN`). Verify each shows
  `authenticated`/`ready` and its tool list is populated
  (`GET /api/v1/mcp-servers` shows both with `auth_status` ok).
- [ ] 10.3 Import the skill once `skills/schemaforge-migration/SKILL.md` exists
  (Task 13, Day 3) — but pre-check now that Settings → Skills accepts a git
  import from `https://github.com/<you>/schemaforge` (repo is public since
  Task 1). If the skill dir doesn't exist yet, import after Task 13 and skip
  this sub-step.
- [ ] 10.4 Record the verified MCP server manifest shapes in this plan's
  "Verified harness reference" (already done) — nothing else to do.

> **Day-2 verification (2026-08-26):** both servers visible
> (`GET /api/v1/mcp-servers` → github authenticated / postgres-prod
> not_required, tools populated under `data`), skills endpoint live
> (`{"data":[]}` — import after Task 13). Scratch harness turns proved
> harness→postgres-prod (`list_tables` → `{"result":["_mcp_probe"]}`) and the
> harness→github path (tool discovered + invoked; the server's schema
> validation errors round-trip correctly). **Day-3 risk found:** the local
> qwen3.8-27b model cannot encode STRING tool arguments — it passes
> JSON-encoded blobs (`repo = '{"repo": ...}'`), so any tool with a string
> arg (get_repo, table_schema, execute_ddl, create_branch, write_file,
> open_pull_request) fails validation in loops and the turn cancels. The
> harness and MCP servers are fine (Day-0 direct probes prove the tools).
> Task 12 MUST test tool-calling on the agent model FIRST; fallback is a
> Cloudflare DeepSeek v4 custom provider (registered exactly like `local`).

---

# Day 3 — Aug 29 · Agent wiring + live end-to-end

## Task 11 — Agent instructions + skill (PR #8)

Steps:
- [ ] 11.1 `agent/instructions.md` (full text — this is the root agent's system
  prompt; it is what makes the run autonomous):

```markdown
# SchemaForge — root agent

You are SchemaForge: an autonomous, AST-aware, zero-downtime database
migration & refactoring agent. You plan, orchestrate, and explain. You do
NOT parse code or count rows yourself — the deterministic engine
(`schemaforge_core`) does that in the sandbox, and you operate on its
JSON output.

## Mission
Given a requested schema change on the connected Postgres database and the
`demo-app` (FastAPI + SQLAlchemy 2.0 + Alembic, checked out in the sandbox),
produce, in order:
1. An impact graph of every affected code path (mermaid + JSON).
2. A data-preserving Alembic migration + updated ORM/DAO/endpoint code.
3. A sandbox verification: migration applied, data parity, application tests,
   EXPLAIN ANALYZE before/after.
4. A safety report in markdown.
5. Production DDL applied ONLY after the human approves the pause.
6. A GitHub pull request containing the migration + code changes.

## Hard rules
- NEVER call `postgres-prod.execute_ddl` expecting it to run without the human.
  The harness pauses that tool for approval. If the human denies, stop,
  explain, and offer the rollback plan. Do not retry.
- The only prod write path is `postgres-prod.execute_ddl`. All other prod
  MCP tools are read-only; treat them that way.
- Never put credentials, DSNs with passwords of systems you don't own, or
  tokens into code, the sandbox, or the PR.
- Analysis = run `python -m schemaforge_core.pipeline ...` in the sandbox and
  read its JSON. Do not re-derive facts by reading files and counting.
- The migration must preserve the API contract encoded in
  `demo-app/tests/` — you may not edit tests.

## Tool inventory
- `postgres-prod` MCP: `list_tables`, `table_schema`, `row_count`, `explain`
  (read-only); `execute_ddl` (APPROVAL-GATED — the only irreversible step).
- `github` MCP: repo/branch/file/PR tools (reversible — not gated).
- Sandbox (Code Mode): python + `schemaforge_core` + `demo-app` checkout at
  `/workspace`; you run alembic/pytest/psql there.
- Skill `schemaforge-migration`: the step-by-step workflow. Follow it.

## Delegation plan
When the user asks for a schema change, immediately create TWO subagents in
parallel:
1. `db-analysis` — instructions: use the postgres-prod MCP tools
   (list_tables, table_schema for every table, row_count for every table,
   explain on the queries in demo-app/queries/bench.sql) and return a JSON
   object in the engine's snapshot shape so it can be written to
   out/db.json verbatim: {tables: {<name>: {name, columns: [{name,
   data_type, nullable, default}], indexes: [{name, columns, unique}],
   foreign_keys: [{name, column, ref_table, ref_column}], row_count}},
   explain: {<query_name>: <plan_text>}}.
2. `code-analysis` — instructions: in the sandbox, run
   `python -m schemaforge_core.pipeline facts --app demo-app --out out/code.json`
   and return the JSON content of that file.

Subagents run in parallel and cannot see each other's results, so each one
returns only what IT can produce on its own (db facts, or code facts). Back
in the root, you merge: write `out/db.json` from the db-analysis JSON, write
`out/code.json` from the code-analysis JSON, then run
`pipeline graph --db out/db.json --code out/code.json --out out/graph.json
--mermaid out/graph.mmd` and `pipeline impact --tables <changed tables>`
yourself, and present the mermaid graph to the user.

## Workflow (mirror of the skill — order matters)
1. Clarify the change (ask_user_question if genuinely ambiguous).
2. Spawn the two subagents (parallel).
3. Merge into the impact graph; show the user the mermaid graph + the list of
   impacted files/endpoints.
4. Plan the migration: expand -> backfill -> contract. Check
   `reference/post-split/` ONLY if you are stuck (and say so to the user if
   you consult it).
5. In the sandbox: author the Alembic revision (revision "0002", down
   "0001") + edit `demo-app/app/models.py`, routers, etc. Then run
   `sandbox_setup.sh` if not already run, then `pipeline verify` with the
   parity SQL you write (model it on the data-preservation invariants of
   the specific change).
6. Present the safety report (markdown) and STOP. Wait for the user.
7. On approval: generate the exact SQL with
   `cd demo-app && alembic upgrade head --sql` (in the sandbox), then call
   `postgres-prod.execute_ddl` with that SQL.
8. Open the GitHub PR: push the modified files (migration + code) to a new
   branch `schemaforge/<slug>` via the github MCP and create the PR with a
   description that embeds the safety report and the impact graph.
9. Summarize: what changed, what was verified, where the PR is, what the
   rollback is (`alembic downgrade -1` on prod).

## Output contract
- End every phase with one status line + artifact paths.
- Impact graph: mermaid code block in chat AND saved to `out/graph.mmd`.
- Safety report: markdown; every number must come from a tool result or the
  engine; label estimates as estimates.
- If a step fails twice, stop and report the failure with the exact error —
  do not improvise around safety invariants.
```

- [ ] 11.2 `skills/schemaforge-migration/SKILL.md` (full text):

```markdown
---
name: schemaforge-migration
description: Run the SchemaForge migration workflow — snapshot, impact graph, migration authoring, sandbox verification, safety report, approval-gated production DDL, and the follow-up PR. Use for any requested database schema change.
---

# SchemaForge migration workflow

## When to use
Any user request to change the Postgres schema of `demo-app`
(add/split/drop/rename columns or tables).

## Invariants
1. Production is never written except via `postgres-prod.execute_ddl`, which
   the harness pauses for human approval.
2. All analysis is deterministic: `schemaforge_core` (sandbox) — never
   eyeballed parsing.
3. Tests in `demo-app/tests/` are the API contract; never edit them.
4. The migration must be data-preserving (expand -> backfill -> contract).

## Steps
1. Sandbox bootstrap (once per session):
   `bash /workspace/scripts/sandbox_setup.sh` — expect `SANDBOX_READY`.
2. DB facts (subagent `db-analysis` or directly): postgres-prod MCP
   `list_tables` + `table_schema` + `row_count` + `explain` over
   `demo-app/queries/bench.sql` → save to `/workspace/out/db.json` in the
   engine's snapshot shape (tables map: name → {name, columns[{name,
   data_type, nullable, default}], indexes, foreign_keys, row_count}).
3. Code facts (subagent `code-analysis` or directly):
   `python -m schemaforge_core.pipeline facts --app demo-app --out out/code.json`.
4. Graph + impact:
   `python -m schemaforge_core.pipeline graph --db out/db.json --code out/code.json --out out/graph.json --mermaid out/graph.mmd`
   `python -m schemaforge_core.pipeline impact --db out/db.json --code out/code.json --tables <changed>`
   Show the mermaid to the user.
5. Baseline: `pipeline snapshot --dsn $DATABASE_URL --out out/db_before.json`
   and `pipeline bench --dsn $DATABASE_URL --queries demo-app/queries/bench.sql --out out/explain_before.json`
   (run against the SANDBOX dsn — the sandbox DB mirrors prod's pre-migration state).
6. Author the migration in `/workspace/demo-app`: new alembic revision
   (0002) + code edits. Write a parity SQL file for THIS change.
7. Verify:
   `pipeline verify --dir demo-app --dsn $DATABASE_URL --baseline out/db_before.json --parity-sql <your parity file> --queries demo-app/queries/bench.sql --explain-before out/explain_before.json --out out/report.md`
   Exit 0 + all PASS is required before step 8.
8. Measure DDL wall time in the sandbox (for the report's lock estimate):
   time the `alembic upgrade head` on a re-seeded copy, or wrap the DDL
   statements with `time.perf_counter()` in a Code Mode script; report
   "DDL took X ms on 100k rows (sandbox)".
9. Present `out/report.md` in chat and STOP — wait for the user's approval.
10. On approval: `cd demo-app && alembic upgrade head --sql` (sandbox) →
    `postgres-prod.execute_ddl(<that SQL>)`. Verify with `table_schema` +
    `row_count` after it returns.
11. PR: github MCP → push modified files to branch `schemaforge/<slug>` →
    create PR (body = safety report + impact mermaid).
```

- [ ] 11.3 `scripts/apply_agent.py` (full code):

```python
"""Create/update the 'schemaforge' agent in the running TrueForge instance."""
from __future__ import annotations

import json
import os
from pathlib import Path

import httpx

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")
HERE = Path(__file__).resolve().parent


def main() -> None:
    instructions = (HERE.parent / "agent" / "instructions.md").read_text()
    manifest = {
        "model": {"name": os.environ.get("SCHEMAFORGE_MODEL", "local/qwen3.8-27b")},
        "instructions": instructions,
        "mcp_servers": [
            {
                "name": "postgres-prod",
                "url": os.environ.get("POSTGRES_MCP_URL", "http://localhost:8001/mcp"),
                "enable_tools": ["@all"],
                "preload": True,
                "require_approval_for_tools": ["@write", "@destructive"],
            },
            {
                "name": "github",
                "url": os.environ.get("GITHUB_MCP_URL", "http://localhost:8002/mcp"),
                "enable_tools": ["@all"],
                "preload": False,
                "require_approval_for_tools": [],
            },
        ],
        "skills": ["schemaforge-migration"],
        "config": {
            "sandbox": {"enabled": True},
            "dynamic_sub_agents": {"enabled": True},
            "generative_ui": {"enabled": True},
            "ask_user_questions": {"enabled": True},
            "iteration_limit": 60,
        },
    }
    with httpx.Client(base_url=BASE, timeout=30) as client:
        existing = client.get("/api/v1/agents/schemaforge")
        if existing.status_code == 200:
            resp = client.put("/api/v1/agents/schemaforge", json={"manifest": manifest})
        else:
            resp = client.post("/api/v1/agents", json={"name": "schemaforge", "manifest": manifest})
    if resp.status_code >= 400:
        raise SystemExit(f"agent upsert failed: {resp.status_code} {resp.text}")
    print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()
```

- [ ] 11.4 `scripts/import_skill.py` (full code):

```python
"""Import the schemaforge-migration skill from this repo into TrueForge."""
from __future__ import annotations

import json
import os
import sys

import httpx

BASE = os.environ.get("TRUEFORGE_URL", "http://localhost:8790")
REPO = os.environ["GITHUB_REPO_URL"]  # e.g. https://github.com/<you>/schemaforge


def main() -> None:
    manifest = {
        "type": "git",
        "url": REPO,
        "ref": "main",
        "path": "skills/schemaforge-migration",
        "description": "SchemaForge migration workflow",
    }
    with httpx.Client(base_url=BASE, timeout=60) as client:
        resp = client.post("/api/v1/settings/skills", json={"manifest": manifest})
    if resp.status_code == 409:
        resp = client.put("/api/v1/settings/skills", json={"manifest": manifest})
    if resp.status_code >= 400:
        sys.exit(f"skill import failed: {resp.status_code} {resp.text}")
    print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()
```

  (If the API rejects the skill manifest shape, fall back to the UI:
  Settings → Skills → import from git, URL = repo, path =
  `skills/schemaforge-migration`, ref = `main`. Verify with
  `GET /api/v1/skills` — the skill appears with name `schemaforge-migration`.)

- [ ] 11.5 Register + verify:

```bash
set -a; source .env; set +a
.vevn/bin/python scripts/import_skill.py     # then verify GET /api/v1/skills
.vevn/bin/python scripts/apply_agent.py      # then verify GET /api/v1/agents/schemaforge
curl -s "$TRUEFORGE_URL/api/v1/agents" | .vevn/bin/python -m json.tool | grep -A3 schemaforge
```

- [ ] 11.6 Branch `feat/agent-wiring`, PR #8 (attach the agent JSON in the
  description). Qodo → merge.
- [ ] 11.7 **Daytona dry-run** (throwaway session — do this before Task 12,
  first thing on Day 3): in a NEW chat with the `schemaforge` agent, send
  exactly:
  "In the sandbox, run `bash scripts/sandbox_setup.sh`, then run
  `python -m schemaforge_core.pipeline snapshot --dsn
  postgresql://postgres:postgres@localhost:5432/bookstore --out out/db.json`.
  Report the number of tables found. Stop there — do nothing else."
  Daytona's environment itself (image, apt, network, Postgres, deps) was
  already proven in 9.5 via the CLI — this dry-run checks what only the
  HARNESS can check: how the repo reaches /workspace when TrueForge
  provisions the sandbox (the laptop filesystem is not visible to a cloud
  sandbox; if the repo is absent there, prepend a `git clone` of the public
  repo to `sandbox_setup.sh`), plus the full wiring (skill load, MCP
  bridges, Code Mode) in one cheap turn. Fix any breakage on
  `fix/sandbox-rehearsal` (PR #7b) before the live run.

> **Day-3 verification (2026-08-27):** all live fixes landed in PR #14
> (feat/agent-wiring): agents are keyed by generated id (upsert = list by
> name → PUT /agents/{id}); AgentSpec mcp_servers carry NO url (servers are
> referenced by name); skill manifest requires `name`; import_skill.py 409
> retry had to live INSIDE the httpx context; sandbox_setup.sh clones the
> public repo into the empty harness sandbox (+chown of the pre-existing
> root-owned /workspace) before provisioning. Skill registered
> (GET /api/v1/skills → [schemaforge-migration]), agent registered.
> **Model decision (live-tested):** qwen3.8-27b CANNOT encode string tool
> args (get_repo/table_schema/execute_ddl all fail validation in loops →
> cancelled turns). Cloudflare DeepSeek v4-flash registered as custom
> provider `cloudflare` (Workers AI OpenAI-compatible base_url, models
> deepseek-v4-flash / deepseek-v4-pro) and PROVEN: get_repo string-arg call
> round-tripped in 15.5s (REPO=ronakgupta03/schemaforge). Agent model is now
> `cloudflare/deepseek-v4-flash` (SCHEMAFORGE_MODEL in .env); qwen remains
> the offline fallback. The Day-3 live run therefore uses the cloud model —
> network dependency is the tradeoff, acceptable for the demo.

## Task 12 — LIVE end-to-end run (the demo)

This is the highest-risk task. Budget 3–4 iterations. Each iteration: fresh
session → send the request → watch where it breaks → fix instructions/skill →
re-run.

Steps:
- [ ] 12.1 Reset prod to pre-split state:

```bash
docker compose -f scripts/prod-postgres/docker-compose.yml down -v
docker compose -f scripts/prod-postgres/docker-compose.yml up -d
bash scripts/seed_prod.sh   # 200k users / 5k books, pre-split schema
```

- [ ] 12.2 Open a NEW chat with the `schemaforge` agent in the TrueForge UI
  and send (exactly this phrasing — it's the video line):

```
Split the users table into users and user_profiles.
user_profiles gets id, user_id (1:1 FK), address, date_of_birth.
users keeps id, name, email.
The API response shape of /users must not change.
```

- [ ] 12.3 Watch for the required beats (checklist — all must appear in the
  transcript/session):
  - [ ] `thread.created` × 2 (db-analysis + code-analysis subagents run in
        parallel — visible as two thread blocks in the UI).
  - [ ] postgres-prod MCP tool calls: `list_tables`, `table_schema`,
        `row_count`, `explain`.
  - [ ] sandbox `sandbox.created` + Code Mode execution of
        `sandbox_setup.sh` and `pipeline facts/graph/impact`.
  - [ ] mermaid impact graph shown in chat (subagent results merged by root).
  - [ ] alembic revision + code edits authored in the sandbox.
  - [ ] `pipeline verify` run: alembic upgrade + parity + pytest + EXPLAIN.
  - [ ] safety report markdown in chat with real numbers.
  - [ ] **`tool.approval_required` on `postgres-prod.execute_ddl` — the chat
        PAUSES and shows the approval UI. (This is the money shot.)**
  - [ ] Approve → DDL runs → post-apply `table_schema`/`row_count` show the
        new schema with all 200k rows intact.
  - [ ] GitHub MCP: branch `schemaforge/split-users` + PR created.
- [ ] 12.4 Verify the agent's PR: it contains the alembic revision + code
  changes; Qodo reviews it (this is Qodo evidence #2 — an agent-created PR).
  Fix anything Qodo flags as High; the PR can remain OPEN for the demo (or
  merge after the video).
- [ ] 12.5 Diff the agent's output against `reference/post-split/`
  (`diff -r` on the 4 changed files + the revision). Any semantic gap is a
  note for the README "what the agent got right/wrong" section — honesty
  point for the judges.
- [ ] 12.6 Re-run resilience check (hackathon criterion "session holds
  together across reconnects"): with the session still open, kill the TrueForge
  process (`pkill -f trueforge`), restart it, reopen the session, and confirm
  history + pending state survive. (If a turn was mid-flight, confirm
  `GET /turns/{id}` returns the final state.)
- [ ] 12.7 Generative UI check: confirm how the safety report renders
  (generative_ui is on). If the UI renders markdown/mermaid natively — great.
  If not: the fallback is already built in — the agent also saves
  `out/report.md` in the sandbox and `file_downloads` is enabled by default,
  so the user can download the report. Note which mode worked in the README.

**Acceptance:** all 12.3 beats observed in one session (or the beats observed
across ≤3 sessions with fixes in between, and ONE clean session recorded for
the video). The PR exists. Prod DB is post-split with 200k rows intact.

## Task 13 — Demo script + rehearsal (no PR)

- [ ] 13.1 Write `docs/demo-script.md` — the exact 3-minute script:

```markdown
# SchemaForge demo script (3:00)

## 0:00–0:20 — Hook
"Every schema change in production is a gamble: you don't know which code
paths break, how long the lock lasts, or whether data survives. SchemaForge
removes the gamble — it proves the migration safe before you approve it."

## 0:20–0:50 — Setup shot
Show: TrueForge chat, the schemaforge agent selected. One sentence:
"Two real tools via MCP — our production Postgres and GitHub — plus a
Daytona sandbox. The only prod write path is one approval-gated tool."

## 0:50–1:20 — The request + subagents
Send: "Split the users table into users and user_profiles…"
Zoom in on: two subagents spawn in parallel (db-analysis drives the Postgres
MCP, code-analysis runs the AST engine in the sandbox). Tool calls scroll:
list_tables, table_schema, row_count…

## 1:20–1:50 — Impact graph
The mermaid graph appears: table → model → DAO → endpoint.
"This is the answer to 'what breaks if I change this column' — computed
deterministically, not by asking the model to grep."

## 1:50–2:25 — Sandbox proof
Code Mode runs: alembic upgrade, parity check, pytest, EXPLAIN ANALYZE.
The safety report card: PASS/PASS/PASS, 200k rows preserved, DDL 340 ms on
100k rows, rollback = alembic downgrade -1.

## 2:25–2:50 — THE GATE
"Apply to production?" — the chat PAUSES. The execute_ddl call is waiting.
Click APPROVE. DDL runs. table_schema confirms the new shape.
Then: "and it opens the PR for you" — show the PR with the migration + diff.

## 2:50–3:00 — Close
"Built on TrueForge: real MCP tools, sandbox code execution, parallel
subagents, a native approval gate, and one session that survived a restart.
Qodo reviewed every PR — evidence in the README."
```

- [ ] 13.2 Rehearse the full run twice with OBS recording (screen = chat UI +
  terminal showing MCP servers; 1080p; mic optional). Reset prod between
  takes (12.1 commands).

---

# Day 4 — Aug 30 · Ship

## Task 14 — README + Qodo evidence (PR #9)

- [ ] 14.1 Rewrite `README.md` (full final text — keep under ~150 lines):

```markdown
# SchemaForge

**Autonomous, AST-aware, zero-downtime database migration & refactoring
agent built on [TrueForge](https://trueforge.dev).**

You ask in plain English — *"split `users` into `users` +
`user_profiles`, keep the API identical."* SchemaForge answers with a
proven-safe change: an impact graph of every affected code path, a
data-preserving Alembic migration, sandbox verification (tests + data
parity + EXPLAIN ANALYZE), a safety report, and — **only after you
approve** — the DDL applied to production plus a GitHub pull request with
the migration and refactored code.

## The idea

A schema migration is really *two* coordinated changes: the database AND
the application code that reads and writes it. Doing either side alone is
how outages happen. SchemaForge treats the pair as one unit:

```
intent → analyze (deterministic) → impact graph → plan
      → generate (migration + code) → prove it in a sandbox
      → safety report → HUMAN APPROVAL → apply to prod → PR
```

**The analysis is not the LLM.** `schemaforge_core` (Python `ast` +
`sqlparse` + `pg_catalog`) extracts the facts — model↔table mappings,
column attribute accesses, raw-SQL table references, FastAPI endpoints —
and builds the impact graph as JSON. The LLM plans over the graph,
authors the migration, and explains. Deterministic facts, agentic
judgment.

## Architecture

- **TrueForge** (local, `:8790`) runs the root agent
  (`local/qwen3.8-27b`, a local llama.cpp server registered as a `custom`
  OpenAI-compatible provider) with
  the `schemaforge-migration` skill (git-imported).
- **MCP, real tools:**
  - `postgres-prod` — *our own* FastMCP server (`mcp-servers/postgres-mcp/`)
    over the "production" Postgres. Read-only introspection + one
    `execute_ddl` tool annotated `destructiveHint`, which TrueForge's
    default `require_approval_for_tools: ["@write","@destructive"]`
    resolves to the **approval pause**.
  - `github` — GitHub MCP server; branches/PRs (reversible → not gated).
- **Daytona sandbox:** in-sandbox Postgres (100k seed rows), the repo
  checkout, `alembic`, `pytest`, and the deterministic engine. The sandbox
  DB is accessed directly (psycopg); prod is only reachable through MCP.
- **Subagents:** `db-analysis` (drives the Postgres MCP) and
  `code-analysis` (runs the engine in the sandbox) run in parallel; the
  root merges their results into the impact graph.
- **Safety report:** schema diff, impacted files/endpoints, test + parity
  results, EXPLAIN ANALYZE before/after, measured DDL wall time, rollback
  plan. Every number comes from a tool result or the engine.

## The demo (3-minute video)

[VIDEO LINK — fill after upload]

One run: split `users` → `users` + `user_profiles` on a 200k-row "prod"
Postgres. The approval pause is the centerpiece — the agent literally
stops and waits for a human before the only irreversible action.

## Run it yourself

Prereqs: Docker, Python 3.12+ (uv), a GitHub PAT, a local llama.cpp server
at `http://localhost:8000/v1`, a Daytona account (API key from
[app.daytona.io/dashboard/keys](https://app.daytona.io/dashboard/keys)), the
[TrueForge](https://trueforge.dev) local install (`npx @truefoundry/trueforge`).

```bash
git clone https://github.com/<you>/schemaforge && cd schemaforge
cp .env.example .env            # fill in your keys
uv pip install --python .vevn/bin/python -e core -r demo-app/requirements.txt -r mcp-servers/postgres-mcp/requirements.txt

# 1. "production" DB (local docker, owned demo data)
docker compose -f scripts/prod-postgres/docker-compose.yml up -d
bash scripts/seed_prod.sh

# 2. MCP servers (:8001 postgres, :8002 github)
bash scripts/run_mcp_servers.sh

# 3. TrueForge setup (models, skill, agent)
set -a; source .env; set +a
# (only if your TrueForge has no Daytona key yet — check Settings → Sandbox providers)
curl -s -X PUT $TRUEFORGE_URL/api/v1/settings/sandbox-providers \
  -H 'content-type: application/json' \
  -d '{"manifest":{"type":"daytona","auth":{"api_key":"'"$DAYTONA_API_KEY"'"},"exec_timeout_ms":120000,"auto_stop":30,"auto_archive":1440,"auto_delete":10080}}'
.vevn/bin/python scripts/setup_local_model.py
.vevn/bin/python scripts/import_skill.py
.vevn/bin/python scripts/apply_agent.py

# 4. Chat with the agent
#    "Split the users table into users and user_profiles. user_profiles
#     gets id, user_id (1:1 FK), address, date_of_birth. users keeps id,
#     name, email. The API response shape of /users must not change."
#    Approve the pause. Watch the PR appear.

# Tests
.vevn/bin/pytest core/tests -q
docker compose -f demo-app/docker-compose.dev.yml up -d
.vevn/bin/pytest demo-app/tests -q
```

## Repository map

| Path | What |
|---|---|
| `core/` | deterministic engine (snapshot, code facts, impact graph, pipeline, report) |
| `demo-app/` | the migrated application (pre-split state on `main`) |
| `reference/post-split/` | golden outcome — what the agent should reproduce |
| `mcp-servers/postgres-mcp/` | our FastMCP prod server (approval-gated DDL) |
| `skills/schemaforge-migration/` | the agent's workflow skill |
| `agent/instructions.md` | root-agent system prompt |
| `scripts/` | setup/run scripts (models, skill, agent, MCP, seeding, sandbox) |

## Qodo Code Review Evidence

Every substantive change landed on `main` via a GitHub PR reviewed by
Qodo (direct pushes to main were not used).

| PR | Content | Qodo outcome |
|---|---|---|
| [#1](PR-1-LINK) | repo hygiene + plan | <fill: findings & resolution> |
| [#2](PR-2-LINK) | Postgres MCP server + prod scripts | <fill> |
| [#3](PR-3-LINK) | demo-app + Alembic baseline + contract tests | <fill> |
| [#4](PR-4-LINK) | core: models + db_snapshot | <fill> |
| [#5](PR-5-LINK) | core: code_facts | <fill> |
| [#6](PR-6-LINK) | core: impact_graph + pipeline + report | <fill> |
| [#7](PR-7-LINK) | golden post-split reference | <fill> |
| [#8](PR-8-LINK) | agent instructions + skill + apply scripts | <fill> |
| [#9](PR-9-LINK) | this README | <fill> |

Representative PR: [LINK] — Qodo flagged <what>, we <how resolved/dismissed>.

Notably, Qodo also reviewed the **agent-created migration PR** (PR #<N>,
opened by SchemaForge itself via the GitHub MCP): <what it surfaced>.

## What we'd do next

- More migration patterns (column type changes, table renames, index-only
  changes) as reusable "strategy cards" in the skill.
- Multi-language code facts (tree-sitter for Go/Java/Rust).
- Lock-duration modeling from real table sizes (pg_stats) instead of
  sandbox wall-time extrapolation.
- `pgroll`-style expand/contract for online DDL on very large tables.
- CI: run the agent against the demo-app on every push (regression).
```

- [ ] 14.2 Fill the Qodo table with real PR links + one-line outcomes; pick
  the most interesting PR as "representative" with a 2–3 sentence
  writeup of what Qodo surfaced and how it was resolved/dismissed.
- [ ] 14.3 Branch `docs/readme-final`, PR #9. Qodo → merge.

## Task 15 — Submission (deadline 20:00 London)

- [ ] 15.1 Final clean demo take (video ≤ 3:00) from the cleanest Task 12
  session (or a fresh re-run with prod reset). Export 1080p.
- [ ] 15.2 Upload video (YouTube unlisted or Loom) → put the link in the
  README (PR #10 if time permits, else in the submission form).
- [ ] 15.3 Write the short submission write-up (what the agent does, how it
  uses TrueForge: MCP real tools, sandbox Code Mode, subagents, approval
  gate, session persistence; one paragraph each).
- [ ] 15.4 Submit: public repo URL + video + write-up via the hackathon form
  (https://forms.gle/dNHFh7wH8uJj4bZH8) — **before Aug 30, 20:00 London**.
- [ ] 15.5 Post the social proof (swag track): 2–3 posts (X/LinkedIn) with
  the demo clip + the approval-pause moment; link the repo.
- [ ] 15.6 Leave the agent-created PR open (judges can watch Qodo review it).

---

# Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Agent stalls / goes off-script mid-pipeline | Medium | Skill encodes exact commands; `reference/post-split/` is the scripted fallback (run the golden path via Code Mode manually if needed — the demo still shows every TrueForge beat); instructions say "stop and report after 2 failures" |
| FastMCP streamable-HTTP ↔ TrueForge client mismatch | Low-Med | Task 3.6 smoke test happens on Day 0, not Day 3; fallback: `mcp-proxy` or the official `server-postgres` over HTTP |
| External GitHub MCP server (GongRzhe) unavailable | Resolved | Repo 404'd on Day 0; replaced with in-repo FastMCP server (`mcp-servers/github-mcp/server.py`): get_repo / branch_exists / create_branch / write_file / open_pull_request |
| Daytona sandbox missing apt/network or slow first boot | Medium | Triple-checked before the demo: Day-2 Docker rehearsal (9.2–9.3, script logic), Day-2 **Daytona CLI rehearsal (9.5, the real platform)** with recorded wall times, and the Day-3 harness dry-run (11.7); `sandbox_setup.sh` is idempotent; `daytona ssh` for live debugging |
| EXPLAIN on prod refused by judges as "not production" | Low | README is explicit: prod = local Docker Postgres with 200k rows, owned demo data (hackathon rule: connect only what's yours); the *architecture* is what generalizes |
| Local llama.cpp server down or too slow for the demo | Medium | Task 2.2/2.5/2.6 verify reachability, a harness smoke test, and a tok/s baseline on Day 0; if the baseline is too slow for a live 3-min video, record the live run earlier in the day and cut the video; the previous provider's models stay registered until the smoke passes |
| Qodo doesn't review a PR | Low | `/agentic_review` comment; one installation covers the repo |
| Deadline pressure | Medium | Day 4 is video+README only; if Day 3's live run needs >1 full day, cut the PR-creation beat (agent stops at approval + apply; PR is opened by hand from the same files) — the approval gate is non-negotiable, the PR beat is cuttable |

# Judging-criteria → deliverable map

| Criterion | Where it's demonstrated |
|---|---|
| Potential impact | Zero-downtime migrations are a real outage class; the pattern (analyze → prove → gate) generalizes to any schema change |
| Creativity / originality | Deterministic AST engine + LLM planner split; our own MCP server as the gated write path; golden-reference design |
| Technical excellence | TDD'd pure-Python core with stable JSON contracts; alembic/pytest/EXPLAIN in one pipeline; 12.5 agent-vs-golden diff |
| Sponsor tools (TrueForge central) | MCP (2 real servers), sandbox Code Mode, parallel subagents, native approval gate, skills, session persistence across restart (12.6) |
| Sponsor tools (Qodo) | 9 reviewed PRs + an **agent-created** PR reviewed by Qodo |
| Control & safety | Single gated write path, DDL-only guardrail in the tool, read-only prod by default, tests-as-contract, rollback in the report |
| Presentation | 3-min script with the pause as the centerpiece; public reproducible repo; honest "what we'd do next" |

# Execution handoff

Two ways to execute this plan:

1. **Subagent-driven (recommended for the independent slices):** each PR-sized
   task (1, 3, 4, 5, 6, 7, 8, 11, 14) is a self-contained unit with a clear
   acceptance check — dispatch one subagent per task, serially (they share
   `main`), each ending at "PR open + Qodo reviewed". Tasks 2, 10, 12, 13,
   15 are interactive (live instance / demo / submission) and stay inline.
2. **Inline:** execute the tasks in order in this session; slower but zero
   handoff friction, and Day 3's live run benefits from the session already
   holding all the context.

Suggested split: inline Day 0 (setup + local model registration + MCP smoke test), then
subagents for the Day 1–2 code tasks in sequence (one at a time, each
finishing its PR), then inline for Day 3 (live run) and Day 4 (ship).
