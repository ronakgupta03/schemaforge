---
name: schemaforge-migration
description: Run the SchemaForge migration workflow against ANY git repo + Postgres database — snapshot, impact graph, migration authoring, sandbox verification, safety report, approval-gated production DDL, and the follow-up PR/commit. Use for any requested database schema change.
---

# SchemaForge migration workflow

## When to use
Any user request to change the Postgres schema of the connected database
(add/split/drop/rename columns or tables), for any application repo and any
Postgres URL (local, Docker, Neon, …). The repo and database are supplied by
the user via the SchemaForge settings (Postgres DSN + GitHub repo); nothing
here is tied to a specific codebase.

## Prerequisites — STOP if missing
1. **Production database.** The `postgres-prod` MCP tools must be configured
   with a `DATABASE_URL` (Settings → SchemaForge → Postgres DSN, or
   `POST /config` on the postgres-mcp config server). If any `postgres-prod`
   tool returns `not configured`, or a connection/auth error, **STOP
   immediately**: call `ask_user_question` asking the user to provide/configure
   the Postgres DSN, and wait for their answer. Do NOT proceed, do NOT fall
   back to the sandbox database for "production" facts — the sandbox DB is a
   rehearsal copy, never a substitute for the real one.
2. **Repository.** The github MCP must be configured with the repo
   (`Settings → SchemaForge → GitHub connector`: token + `owner/name`). If
   unset, ask the user for the repo before cloning.
3. If either is missing and the user answers, re-check before continuing.

## Invariants
1. Production is never written except via `postgres-prod.execute_migration`
   (full batches) or `postgres-prod.execute_ddl` (pure DDL), which the
   harness pauses for human approval.
2. All analysis is deterministic: `schemaforge_core` (sandbox) — never
   eyeballed parsing.
3. The app's tests are the API contract; never edit them to make the
   migration pass.
4. The authored revision's `downgrade()` MUST guard every `SET NOT NULL` on a
   column that was backfilled from a nullable state: add a `DO` block that
   `RAISE EXCEPTION`s if any row would violate the constraint, BEFORE the
   `ALTER … SET NOT NULL`. (Qodo caught this exact bug class on an early
   agent-authored PR: the downgrade left values `NULL` for rows without a
   matching profile row, then the `NOT NULL` alteration failed cryptically.
   Do not regress it.)
5. The pre-approval flow must fit inside the server's execution window
   (default 600 s): no DDL timing / re-seeding / re-verifying before the
   approval pause — measure DDL wall time only after approval.

## Steps

### 0. Configuration check
Confirm `postgres-prod` responds to a read tool (`list_tables`) before any
analysis. If it errors with `not configured` or a connection failure, STOP
and ask the user for the DSN (Prerequisite 1). Confirm `GITHUB_REPO_URL` is
known (Prerequisite 2); ask if missing. Also note the user's **delivery
instruction**: PR (default when the github MCP is attached), commit-only (no
PR), or artifact-only (no GitHub at all). If the request is ambiguous, ask
via `ask_user_question` at the approval pause.

### 1. Sandbox bootstrap (once per session)
Clone the USER's repo (not the engine) into the sandbox:
```bash
git clone --depth 1 ${GITHUB_REPO_URL} /workspace/app || test -d /workspace/app/.git
cd /workspace/app
```
If the clone fails with permission denied on `/workspace`, run
`sudo chown -R daytona:daytona /workspace` first, then re-clone.

Provision the app in the sandbox: create/activate a venv, install the app's
dependencies (discover `requirements.txt` / `pyproject.toml` / `Pipfile`),
install `schemaforge_core` (the deterministic engine) into the same venv,
start the sandbox Postgres, create the app's database, and bring it to its
baseline (e.g. `alembic upgrade head` if the app uses Alembic — else the
app's own migration/DDL). The sandbox DB mirrors production's pre-change
state: if the app ships seed data, load it so EXPLAIN ANALYZE is meaningful.

In every later shell, source the venv activation so `python`/`alembic`/
`pytest`/`sf-pipeline` resolve to it.

### 2. DB facts
Subagent `db-analysis` or directly: postgres-prod MCP `list_tables` +
`table_schema` + `row_count` for every table + `explain` on 2–3
representative queries (derive them from the impact graph's raw-SQL refs or
the app's own query files; do not assume a specific path). Save to
`/workspace/out/db.json` in the engine's snapshot shape.

### 3. Code facts
Subagent `code-analysis` or directly:
`python -m schemaforge_core.pipeline facts --app /workspace/app --out out/code.json`.

### 4. Graph + impact
```bash
python -m schemaforge_core.pipeline graph --db out/db.json --code out/code.json --out out/graph.json --mermaid out/graph.mmd
python -m schemaforge_core.pipeline impact --db out/db.json --code out/code.json --tables <changed tables>
```
Show the mermaid graph to the user.

### 5. Baseline (sandbox DB)
```bash
sf-pipeline snapshot --dsn $DATABASE_URL --out out/db_before.json
sf-pipeline bench --dsn $DATABASE_URL --queries <app query file(s)> --out out/explain_before.json
```

### 6. Author the migration
In `/workspace/app`: add a new revision to the app's migration chain (e.g.
Alembic `alembic revision`) with the expand → backfill → contract pattern,
plus the ORM/endpoint code edits. Write a parity SQL file for THIS change.
Stage the new migration as intent-to-add so it appears in the diff:
`git add -N <migration file>` (do NOT fully stage unrelated dirt).

### 7. Verify in the sandbox
```bash
sf-pipeline verify --dir /workspace/app --dsn $DATABASE_URL --baseline out/db_before.json --parity-sql <parity file> --queries <app query file(s)> --explain-before out/explain_before.json --out out/report.md
```
This writes `out/report.md` AND `out/verify.json` (the machine-readable
evidence the UI renders). Confirm migration PASS, tests PASS, parity PASS
before continuing. Then `git add -N <migration file>` (if not already) &&
`git diff > /workspace/out/diff.patch` (code changes only).

### 8. Present report and PAUSE
Present `out/report.md` in chat and call `ask_user_question` with options
Approve / Deny / Request changes — never end the turn silently after the
report. If the user's delivery instruction is ambiguous, include a delivery
question in the same pause (e.g. "Open a PR or commit only?").

### 9. On approval — production apply
Learn the current revision: `alembic current` (sandbox DB, in the app dir).
Generate the offline SQL for ONLY the new revision:
`cd /workspace/app && (alembic upgrade <current>:head --sql > /workspace/out/migration.sql)`.
Then call `postgres-prod.execute_migration(<that SQL>)`. After it returns,
measure the DDL wall time (for the report's lock estimate: time the upgrade
with `time.perf_counter()` in a Code Mode script) and verify with
`table_schema` + `row_count`.

### 10. Delivery — respect the user's instruction
- **PR (default if the github MCP is attached):** push the modified files to
  branch `schemaforge/<change-slug>` via the github MCP (`create_branch` +
  `write_file`), open the PR (`open_pull_request`, body = safety report +
  impact mermaid).
- **Commit-only (user said "no PR" / "just commit"):** `create_branch` +
  `write_file` only. Do NOT call `open_pull_request`. Report the branch name
  and commit.
- **Artifact-only (no github MCP or user said "don't touch GitHub"):** save
  `git diff > /workspace/out/diff.patch` and report the artifact path.
When in doubt, default to PR; when the user has stated a preference, follow
it exactly.

### 11. Qodo review loop (PR delivery only)
After opening the PR, read the review discussions:
`github.get_pull_request(repo, number)` (returns `state`, `reviews`,
`comments`). If review comments exist (e.g. Qodo findings), fix each flagged
issue in the sandbox, re-run the relevant verification, and push the fix to
the same branch with `write_file`. Re-check the PR until the review is clean
or the reviewer stops commenting. If the review has not landed yet (no
comments), do NOT spin: tell the user the PR is open and ask them to say
"check the PR review" once the review is in.

## Output contract
- End every phase with one status line + artifact paths.
- Impact graph: mermaid code block in chat AND saved to `out/graph.mmd`.
- Safety report: markdown; every number must come from a tool result or the
  engine; label estimates as estimates.
- If a step fails twice, stop and report the failure with the exact error —
  do not improvise around safety invariants.