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
| `demo-app/`                     | FastAPI + SQLAlchemy 2.0 + Alembic bookstore (demo target) + fixture scripts: `seed_prod.sh`, `reset_prod_db.sh`, `prod-postgres/`, `.sf-sandbox.env` |
| `reference/post-split/`         | Golden post-split outcome (migration, models, parity SQL)                                                          |
| `mcp-servers/postgres-mcp/`     | Production-Postgres MCP server (read tools + gated`execute_migration`/`execute_ddl`)                           |
| `mcp-servers/github-mcp/`       | GitHub MCP (branch / write_file / open_pull_request — reversible only)                                            |
| `scripts/`                      | `apply_agent.py`, `import_skill.py`, `run_mcp_servers.sh`, `setup_local_model.py`, `patch-trueforge-mermaid.py`, `rehearsal/` |

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
  for tables created by the migration itself (a plain backfill targeting an
  already-existing table is rejected and rolled back); a guarded
  `INSERT … SELECT … WHERE NOT EXISTS` reconciliation is allowed to backfill
  stragglers into an existing table idempotently.
- **Expand-only guard.** `execute_migration` takes a `phase='expand'` mode
  that rejects any `DROP`/`TRUNCATE`/`ALTER`, so an additive apply can never
  remove or modify existing schema — only create new objects and backfill.
- **Two-phase expand/contract (zero-downtime).** For live-traffic splits the
  workflow runs an additive **expand** phase (create + dual-write + backfill)
  that is safe under load, then a later **contract** phase (drop the old
  columns). The contract is gated by `sf-pipeline contract-gate`, which proves
  *no deployed code reads the columns being dropped* — and BLOCKS (rather
  than silently passing) when a requested column is absent from the graph
  (typo or stale DB snapshot). The contract phase can only run after the
  operator deploys the final app build.
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

1. **Models**: Configure LLM provider API keys (OpenAI, Anthropic, Gemini, Cloudflare) and choose the active model for SchemaForge.
2. **MCP Servers**: Inspect discovered MCP servers and toggle which servers are attached to the agent.
3. **Connectors**: Set up the production PostgreSQL connection (database DSN / URL) and the GitHub connector with your token and repository.
4. **Sandbox**: Enable or disable the Daytona sandbox environment used for isolated migration execution and verification.
5. **Apply Agent**: Re-generate the agent manifest and apply it to TrueForge. Unconfigured services are simply omitted: without a Postgres connector, the agent skips prod introspection and apply; without a GitHub connector, it saves `out/diff.patch` locally instead of opening a PR. Nothing crashes.

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
docker compose -f demo-app/prod-postgres/docker-compose.yml up -d
bash demo-app/seed_prod.sh

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

## Resetting the prod database

The demo expects prod in the **pre-split** baseline (alembic `0001`,
200,000 users / 5,000 books). After a live run applies the split, prod is
left post-split as evidence. Before the next take — or whenever
`alembic upgrade head` fails with `Can't locate revision identified by
'0002'` because the DB is stamped at a migration that has since been
reverted out of `demo-app/alembic/versions` — reset it to a clean baseline:

```bash
bash demo-app/reset_prod_db.sh
```

It terminates live connections to the target DB, drops and recreates it
(connecting via the `/postgres` maintenance database, since
`DROP`/`CREATE DATABASE` cannot run in a transaction or against the
`connected DB), then re-runs `demo-app/seed_prod.sh` (0001 baseline +
200k / 5k seed). Point it at a different database with
`DATABASE_URL=postgresql://user:pass@host:5433/bookstore bash demo-app/reset_prod_db.sh`.

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

### PR #31 — Two-phase expand/contract workflow (`feat/two-phase-workflow`, merged `2c68045`)

Qodo surfaced **9 findings across review rounds**; all resolved to **Bugs 0**:

| Finding (severity)                         | What Qodo caught                                                  | Resolution                                                                                                   |
| ------------------------------------------ | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Contract gate cannot become safe (Correctness) | gate ran on the dual-write build and BLOCKED forever            | Reordered: author + deploy the final app first, then re-run the gate on the deployed final code              |
| Contract drops precede app delivery (Reliability) | contract DDL applied before the final app was deployed        | DDL now runs only after the operator confirms the final app is deployed                                      |
| Contract reconciliation always fails (Correctness) | `validate-phase`/`execute_migration` rejected the reconciliation INSERT..SELECT | Guarded `WHERE NOT EXISTS` INSERT..SELECT reclassified phase-neutral and allowed into an existing table |
| Gate can approve unknown columns (Correctness) | an absent/typo column returned SAFE, bypassing the gate          | An absent requested column is now a hard BLOCKER (`kind: absent`)                                            |
| Gate scans unverified checkout (Reliability) | facts scanned the locally-modified sandbox tree, not deployed code | Workflow forces a fresh `git fetch` + `reset --hard` to the operator's deployed branch before facts        |
| Contract SQL range is empty (Correctness)  | `alembic upgrade <current>:head --sql` rendered nothing post-apply | Capture `alembic current` (expand head) before the sandbox apply; render from that revision                  |
| DROP NOT NULL rejected (Correctness)        | expand-phase verb allowlist rejected `ALTER ... SET NOT NULL`     | Contractive `ALTER` sub-actions (drop column / set not null) allowed in the contract phase                    |
| Contract SQL range is empty (dup) (Correctness) | stale inline thread resurfaced                                | Resolved on re-review; threaded review confirmed                                                                 |
| Expand phase call unsupported (Correctness) | workflow referenced an undefined pipeline sub-command            | Fixed in instructions + skill                                                                                  |

### PR #32 — Phased expand/contract reference (`feat/phased-reference`, merged `073ae68`)

Qodo surfaced **4 findings**; the mixed-ALTER smuggling bug and the
nullable-downgrade gap were fixed (contractive-sub-action guard + restored
`NOT NULL` in the downgrade). The two recurring zero-downtime findings
(final-deploy breaks creates, backfill misses concurrent writes) are resolved
by design — the expand makes the dropped column nullable first so the final
app's inserts succeed — with the residual concurrent-write-during-drops gap
documented as a known limitation requiring app-level quiesce, per the
pragmatic zero-downtime scope decision.
Qodo's review comments are visible on each PR; the workflow is a required
hackathon gate, so no substantive change merges without it.

## License

MIT (hackathon project — open source).
