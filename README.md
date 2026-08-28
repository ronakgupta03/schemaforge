# SchemaForge

**Autonomous, AST-aware, zero-downtime database migration & refactoring agent — built on TrueForge.**

SchemaForge treats a schema change as what it really is: a coordinated
database **and** application-code change. It builds a deterministic impact
graph (tables → ORM models → attributes → endpoints), proves the migration
safe inside an isolated sandbox, and only touches production after a
**human approval gate**.

Built for the [Agent Harness Hackathon](https://wearedevs.com) (WeMakeDevs ×
TrueFoundry × Qodo) on the [TrueForge](https://trueforge.dev) agent harness.

## Demo

The exact 3-minute demo script (beats, narration, production notes):
[`docs/demo-script.md`](docs/demo-script.md).

Demo video (1080p, ≤3:00): _link added after the final take_ ·
Submission write-up: [`docs/submission-writeup.md`](docs/submission-writeup.md).

> The built-in TrueForge UI does not render `mermaid` code blocks by
> default (it only syntax-highlights them). If you are running the local
> UI, run `python scripts/patch-trueforge-mermaid.py` once to inject the
> mermaid runtime into the served frontend (idempotent; re-run after any
> `npx` re-fetch). Verified: impact-graph mermaid blocks render as SVG.

## How it works

```
User prompt            e.g. "Split the users table into users and user_profiles"
   │
   ▼
TrueForge root agent (schemaforge)          ── model: cloudflare/deepseek-v4-flash
   │  spawns two parallel subagents
   ├── db-analysis    → postgres-prod MCP (list_tables, table_schema, row_count, EXPLAIN)
   └── code-analysis  → Daytona sandbox: sf-pipeline facts  (stdlib ast + sqlparse)
   │
   ▼
Deterministic engine merges → impact graph (JSON + Mermaid), shown to the user
   │
   ▼
Sandbox: agent authors the Alembic migration + code, runs sf-pipeline verify
   (alembic upgrade · data-parity checks · pytest · EXPLAIN ANALYZE before/after)
   │
   ▼
Safety report → THE GATE: execute_migration pauses for human approval
   │  (one transaction · full rollback on any failure · DDL-only + backfill verbs)
   ▼
Apply to prod → verify row counts → GitHub PR of the migration + refactored code
```

The engine (`schemaforge_core`) is deterministic: it parses the codebase with
the Python `ast` module and introspects the database via
`information_schema` / `pg_catalog`. The LLM plans, orchestrates, and
explains — it never guesses about code or schema.

## Repo layout

| Path                              | What                                                                                                               |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `agent/instructions.md`         | Root-agent system prompt (workflow, hard rules)                                                                    |
| `skills/schemaforge-migration/` | TrueForge skill: the migration workflow                                                                            |
| `core/`                         | `schemaforge_core` — deterministic engine + `sf-pipeline` CLI (snapshot, facts, graph, impact, verify, bench) |
| `demo-app/`                     | FastAPI + SQLAlchemy 2.0 + Alembic bookstore (the demo target)                                                     |
| `reference/post-split/`         | Golden post-split outcome (migration, models, parity SQL)                                                          |
| `mcp-servers/postgres-mcp/`     | Production-Postgres MCP server (read tools + gated`execute_migration`/`execute_ddl`)                           |
| `mcp-servers/github-mcp/`       | GitHub MCP (branch / write_file / open_pull_request — reversible only)                                            |
| `scripts/`                      | `apply_agent.py`, `import_skill.py`, `sandbox_setup.sh`, `seed_prod.sh`, `run_mcp_servers.sh`            |

## Safety model

- **One irreversible path.** The only prod write tools are
  `postgres-prod.execute_migration` / `execute_ddl`, annotated
  `destructiveHint` so TrueForge pauses the turn for approval. Everything
  else is read-only.
- **Transactional.** `execute_migration` runs the whole Alembic batch
  (DDL + backfill + version stamping) in one transaction — any failure
  rolls back to zero partial state. It accepts DDL verbs, data-preserving
  `INSERT … SELECT` backfills, and `alembic_version` bookkeeping; it
  rejects data-table `UPDATE`/`DELETE`/`COPY` and arbitrary `SELECT`.
- **Proven before approval (workflow-enforced).** Migration, data parity,
  application tests, and EXPLAIN ANALYZE all run in the sandbox first, and
  the workflow requires PASS/PASS/PASS before the agent requests approval.
  The *mechanical* gate is the `destructiveHint` annotation on the write
  tools — the harness pauses for a human regardless of what the model did
  or claimed.
- **Backfills cannot duplicate data.** `INSERT … SELECT` is accepted only
  for tables created by the migration itself — a backfill targeting an
  already-existing table is rejected and rolled back.
- **Rollback is real.** The split migration's `downgrade()` is guarded: it
  is blocked with a clear error if any user lacks a profile row, rather
  than fabricating data. (The baseline revision 0001's downgrade is
  destructive by design — it drops the initial schema.)
- **Reversible GitHub actions.** PR/branch creation carries no approval
  requirement — merging is still a human action.

## Run it — one command (npx package)

```bash
npx @schemaforge/schemaforge
```

Boots the full local stack (TrueForge + postgres-mcp + github-mcp + registry
 Evidence UI) and opens the browser at http://localhost:5173. Running
services on the default ports are reused instead of restarted. First run
creates a Python venv and installs the engine + MCP dependencies.

**Configure everything in the UI — nothing is hardcoded.** The Settings tab
has five sections:

  models) and pick the agent's active model.
  be attached to or detached from the agent.
  (Database URL / DSN) and the GitHub MCP at your own token + repo.
  verification).
  and applies it. Unconfigured services are simply omitted: no postgres
  connector → the agent skips prod introspection/apply; no github connector
  → it saves `out/diff.patch` instead of a PR. Nothing crashes.

## Run it — full local stack (all components, dev setup)

```bash
# 0. One-time environment (creates the .vevn venv the scripts use)
uv venv .vevn                                     # Python 3.14, uv
uv pip install --python .vevn/bin/python -e core
uv pip install --python .vevn/bin/python -r demo-app/requirements.txt
uv pip install --python .vevn/bin/python -r mcp-servers/postgres-mcp/requirements.txt
uv pip install --python .vevn/bin/python -r mcp-servers/github-mcp/requirements.txt

# 1. Services
bash scripts/run_mcp_servers.sh      # postgres-mcp :8001, github-mcp :8002
SERVER_EXECUTION_TIMEOUT_SECONDS=1800 npx @truefoundry/trueforge
scripts/patch-trueforge-mermaid.py   # harness on [::1]:8790 (SQLite local mode)

# 2. Provision prod (pre-split baseline: alembic 0001, 200k users / 5k books)
docker compose -f scripts/prod-postgres/docker-compose.yml up -d
bash scripts/seed_prod.sh

# 3. Register the agent + skill (idempotent)
.vevn/bin/python scripts/apply_agent.py
.vevn/bin/python scripts/import_skill.py

# 4. In the TrueForge UI (http://localhost:8790), chat with `schemaforge`:
#    "Split the users table into users and user_profiles. user_profiles
#    gets id, user_id (1:1 FK), address, date_of_birth. users keeps id,
#    name, email. The API response shape of /users must not change."
```

Environment (copy `.env.example`): `TRUEFORGE_URL` (use
`http://[::1]:8790` for API clients — local mode binds IPv6 loopback),
`DATABASE_URL` (prod), `POSTGRES_MCP_URL`, `GITHUB_MCP_URL`,
`GITHUB_PERSONAL_ACCESS_TOKEN`, `GITHUB_REPO_URL` (used by
`import_skill.py`), `DAYTONA_API_KEY`, `SCHEMAFORGE_MODEL` (default
`cloudflare/deepseek-v4-flash`; Cloudflare creds in `~/.zshrc`).

## Qodo Code Review Evidence

Policy: **every substantive change lands via a pull request reviewed by
Qodo** before merge (direct pushes are docs-only). Representative PRs:

### PR #14 — Root agent wiring (`feat/agent-wiring`, merged `785c327`)

Qodo surfaced **9 findings across 4 review rounds** (6 initial + 3 from
re-reviews); each was fixed and re-reviewed to **Bugs 0**:

| Finding (severity)                         | What Qodo caught                                                  | Resolution                                                                                                   |
| ------------------------------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| `run_postgres()` removed (High)          | Edit regression deleted the postgres-runner helper                | Restored; 6 call sites verified                                                                              |
| Impact command lacks`--db/--code` (High) | instructions told the agent to run a broken command               | Fixed in instructions + skill                                                                                |
| Migration SQL rejected (High)              | `execute_ddl` rejected backfills + `alembic_version` stamping | **New `execute_migration` tool**: one transaction with rollback, DDL + `INSERT…SELECT` + stamping |
| Offline SQL replays baseline (High)        | `alembic upgrade head --sql` regenerates 0001                   | Approval SQL now`alembic upgrade 0001:head --sql`                                                          |
| DDL batches can partially apply (High)     | non-atomic multi-statement apply                                  | Single transaction, rollback live-proven (failing stmt → zero partial state)                                |
| Snapshot fields unavailable (Medium)       | `table_schema` lacked defaults/indexes/FKs                      | Enriched to the engine's exact snapshot shape                                                                |
| SQL literals split on`;` (High)          | naive`split(";")` fragments strings                             | Comment/dollar-quote-aware`_split_statements` scanner                                                      |
| Indexes cross schema boundaries (Medium)   | index/FK queries unqualified by schema                            | Schema-qualified to`'public'` (`relnamespace`, `table_schema`)                                         |
| Primary keys disappear (High)              | `ix.indisprimary` filtered out PK indexes                       | Removed filter;`users_pkey` present in `indexes`                                                         |

### PR #12 — Sandbox rehearsal (`feat/sandbox-rehearsal`, merged `7a3a739`)

Qodo: 4 findings, all resolved — a dropped helper call, `_test_dsn` appending
`_test` after the query string (would target the source DB), PEP 668
refusing bare `pip install` on Debian, and a client-only image masking the
missing server install. Fixed with `urlsplit`-based DSN rewriting and
`--break-system-packages` + install-when-client-only.

### PR #15 — Agent-authored migration (opened by the agent itself)

Qodo reviewed the PR the **agent** created (`schemaforge/split-users`,
merged `2857075`) and found **"Profileless users block rollback"**: the
downgrade join leaves `address` NULL for users without a profile row, then
the `NOT NULL` alteration fails. Fixed by a guard that blocks rollback with
an explicit diagnostic when any user lacks a profile (live-verified both
paths; the golden reference received the same guard). Re-review: **Bugs 0**.

Qodo's review comments are visible on each PR; the workflow is a required
hackathon gate, so no substantive change merges without it.

## License

MIT (hackathon project — open source).
