# SchemaForge demo script (3:00)

Verified against the live Task-12 run (2026-08-27, session `01m120emd…`):
prod 200k users split into `users` + `user_profiles`, approval gate fired,
PR #15 opened, Qodo reviewed it clean. Timings below are from that run —
the demo video is an **edited** recording of a fresh run (see Production
notes); only the approval click is shown real-time.

## 0:00–0:20 — Hook
"Every schema change in production is a gamble: you don't know which code
paths break, how long the lock lasts, or whether data survives. SchemaForge
removes the gamble — it proves the migration safe before you approve it."

## 0:20–0:50 — Setup shot
Show: TrueForge chat, the `schemaforge` agent selected, the agent library.
One sentence:
"Two real tools via MCP — our production Postgres and GitHub — plus a
Daytona sandbox. The only prod write path is one approval-gated tool."
Overlay the agent card: model `cloudflare/deepseek-v4-flash`, postgres-prod
preloaded, github deferred, sandbox on, iteration_limit 60.

## 0:50–1:20 — The request + subagents
Send the locked prompt:
> "Split the users table into users and user_profiles. user_profiles gets
> id, user_id (1:1 FK), address, date_of_birth. users keeps id, name,
> email. The API response shape of /users must not change."

Zoom in on: **two subagents spawn in parallel** (db-analysis drives the
postgres-prod MCP; code-analysis runs the AST engine in the sandbox). Tool
calls scroll: `list_tables`, `table_schema` ×3, `row_count` (1 / 5,000 /
**200,000**), `EXPLAIN` ×3, `sf-pipeline facts`.

## 1:20–1:50 — Impact graph
Show the mermaid graph (**26 nodes, 43 edges**): table → model → attr →
endpoint, plus the raw-SQL edges.
"This is the answer to 'what breaks if I change this column' — computed
deterministically by the engine, not by asking the model to grep."

## 1:50–2:25 — Sandbox proof
Code Mode runs in the Daytona sandbox: `alembic upgrade`, data-parity
checks, `pytest` (6 contract tests), `EXPLAIN ANALYZE` before/after.
The safety report card: **migration PASS / tests PASS / parity PASS**,
200,000 rows preserved 1:1, DDL wall time **1,052 ms on 100k rows**,
rollback = `alembic downgrade -1` (guarded: blocked if any user lacks a
profile row).

## 2:25–2:50 — THE GATE
"Apply to production?" — the chat **PAUSES**. The `execute_migration`
call is waiting on human approval. Click **APPROVE**.
"applied 5 migration statement(s) in one transaction" → the agent verifies:
`user_profiles` = 200,000 = `users`, FK + unique constraint confirmed via
`table_schema`.
Then: "and it opens the PR for you" — show PR #15: the 0002 migration +
models/routers diff, reviewable, Qodo-checked.

## 2:50–3:00 — Close
"Built on TrueForge: real MCP tools, sandbox code execution, parallel
subagents, a native approval gate, and a session that survived a server
restart. Qodo reviewed every PR — evidence in the README."

---

## Production notes (record + edit)

1. **Reset prod before the take** (pre-split baseline):
   ```bash
   docker compose -f scripts/prod-postgres/docker-compose.yml down -v
   docker compose -f scripts/prod-postgres/docker-compose.yml up -d
   bash scripts/seed_prod.sh          # alembic 0001 + 200k users / 5k books
   ```
2. **Start the services**: `bash scripts/run_mcp_servers.sh` (postgres-mcp
   :8001, github-mcp :8002), TrueForge on `[::1]:8790`. Confirm agent
   `schemaforge` is registered (`scripts/apply_agent.py` is idempotent).
3. **Record**: full chat UI (browser) + a terminal showing the MCP servers
   (tool traffic). 1080p. Mic optional. One take; edit to the beats above.
4. **The run takes ~15–20 min wall** (live run: sandbox boot + analysis
   ~8 min, authoring + verify ~5 min, apply + PR ~2 min). Edit down: keep
   the subagent spawn, the graph, the report card, and the approval click
   real-time; fast-forward or cut the sandbox install.
5. **If the model pauses at `ask_user_question`** before the tool call
   (as in the live run): answer it on screen ("Approve"), then the
   `execute_migration` approval card appears — that click is the money shot.
6. **429 rate-limit risk** (Cloudflare Workers AI): if a turn dies with
   "Request failed (429)", wait ~5 min and resume in the same session —
   the session continuity beat is part of the demo's story.
7. **After the take**: prod is post-split; reset it again before the next
   take (step 1) — the demo always starts from a pre-split prod.