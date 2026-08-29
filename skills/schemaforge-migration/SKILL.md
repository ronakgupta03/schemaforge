---
name: schemaforge-migration
description: Run the SchemaForge migration workflow against ANY git repo + Postgres database — two-phase zero-downtime (expand → deploy → contract): snapshot, impact graph, additive expand migration + dual-write code, sandbox verification, contract-gate, safety report, approval-gated production DDL, and the follow-up PRs. Use for any requested database schema change.
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
6. **Two-phase.** Never apply a contract migration in the same turn as an
   expand migration. Expand is additive (safe under live traffic); contract
   removes schema and needs the dual-write app deployed first. After the
   expand PR is applied, END THE TURN and wait for the operator to say
   "contract <slug>".
7. **Contract-gate before contract.** Never propose or apply a contract
   migration until the deterministic contract-gate
   (`sf-pipeline contract-gate`) returns `SAFE`. If `BLOCKED`, list every
   blocker and STOP — tell the operator which code still reads the old
   columns and must be deployed first.
8. **Expand is additive only.** Expand migrations use `create_table`,
   `add_column` (nullable or with a default), `create_index`,
   `INSERT..SELECT` backfill, and `alter_column(..., nullable=True)` (DROP
   NOT NULL) on legacy columns the final app will stop writing — NO `drop_*`,
   NO `alter_column(..., nullable=False)` (SET NOT NULL is contractive), NO
   `alter_column(..., type=...)`. `execute_migration(phase='expand')` is an
   additive ALLOWLIST (CREATE, INSERT backfill, ADD COLUMN/CONSTRAINT, ALTER
   COLUMN SET DEFAULT, DROP NOT NULL, VALIDATE CONSTRAINT); everything else
   is rejected, so a mis-authored expand fails safely.
9. **Concurrent-write scope.** The expand backfill + the contract
   reconciliation handle a quiesced/low-write window, and the expand app
   build dual-writes. Truly concurrent writes during the contract drops need
   app-level dual-write or a brief cutover quiesce — the application's
   responsibility, not the migration agent's. State this scope in the safety
   report whenever the target DB is not quiesced.

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
The sandbox starts empty. Determine the target repo, then bootstrap an in-sandbox
Postgres + tooling in ONE call:

1. Resolve the target repo URL:
   - If `GITHUB_REPO_URL` is set in the sandbox environment, use it.
   - Else if the `github` MCP is attached, call `get_repo('')` (empty repo resolves
     to the configured default repo) and use its `clone_url`.
   - Else ask the operator for the GitHub URL of the app you are migrating.
   Do NOT assume any specific repo.
2. Run the generic bootstrap (it ships with this skill), passing the resolved URL:
   `GITHUB_REPO_URL=<url> bash /opt/tfy/skills/schemaforge-migration/sandbox_setup.sh`
   It chowns `/workspace` if needed, starts an in-sandbox Postgres, clones the target
   into `/workspace/app`, installs the app's deps + the SchemaForge core, runs the
   app's migrations (alembic/django auto-detected), and seeds if the repo declares
   `SANDBOX_SEED_CMD` in `.sf-sandbox.env`.
3. Source the activation script in every later shell: `. $HOME/.sfenv-activate.sh`.
   This sets `DATABASE_URL` (in-sandbox), `TEST_DATABASE_URL`, and `APP_DIR`.

All analysis runs against `$APP_DIR` (the target app) and the in-sandbox DB.
Production/cloud DB access is ONLY via the host-side `postgres-prod` MCP tools.

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

## Phase 1 — EXPAND (apply now; additive, safe under live traffic)

### 6. Author the EXPAND migration
In `/workspace/app`: add a new revision `<rev>a_<slug>.py` (e.g. Alembic
`alembic revision`). Additive ONLY — `create_table`, `add_column` (nullable
or with a default), `create_index`, `INSERT..SELECT` backfill, and
`alter_column(..., nullable=True)` (DROP NOT NULL) on any legacy column the
final app will stop writing (so the final app build can insert rows without
it during the expand->contract window). NO `drop_*`, NO
`alter_column(..., nullable=False)` (SET NOT NULL is contractive), NO
`alter_column(..., type=...)` (a type change rewrites the table — it is
contractive). Then validate it:
```bash
sf-pipeline validate-phase --migration <expand file> --phase expand
```
Must exit 0; fix any contract op it flags. Stage the new file intent-to-add
(`git add -N <migration file>`) so it appears in the diff.

### 7. Author the DUAL-WRITE app build
Keep the old columns on the model (the expand migration did NOT drop them)
AND add the new table/relationship; writes go to BOTH the old and new shapes
so the running app keeps serving while the new shape is populated. Use the
impact graph to find every endpoint that reads the old columns and make each
one read the new shape with a fallback to the old (or stay on the old — both
are safe while the old columns still exist). Write a parity SQL file for
THIS change.

### 8. Verify in the sandbox
```bash
sf-pipeline verify --dir /workspace/app --dsn $DATABASE_URL --baseline out/db_before.json --parity-sql <parity file> --queries <app query file(s)> --explain-before out/explain_before.json --out out/report.md
```
This writes `out/report.md` AND `out/verify.json`. Confirm migration PASS,
tests PASS, parity PASS. The old columns still exist after expand, so parity
= the old shape is unchanged AND the new table is backfilled. Then
`git diff > /workspace/out/diff.patch` (code changes only).

### 9. Lock analysis
```bash
sf-pipeline analyze-locks --migration <expand file>
```
If any op is `dangerous` (e.g. SET NOT NULL), rework it into the safe
alternative the report names BEFORE applying. CREATE INDEX CONCURRENTLY and
the CHECK-constraint trick cannot run inside `execute_migration`'s single
transaction — emit those as a separate `execute_ddl` step or an operator
manual note.

### 10. Present report and PAUSE
Present `out/report.md` in chat and call `ask_user_question` with options
Approve / Deny / Request changes — never end the turn silently after the
report. If the user's delivery instruction is ambiguous, include a delivery
question in the same pause.

### 11. On approval — production apply (expand)
Learn the current revision: `alembic current` (sandbox DB, in the app dir).
Generate the offline SQL for ONLY the new revision:
`cd /workspace/app && (alembic upgrade <current>:head --sql > /workspace/out/expand.sql)`.
Then call `postgres-prod.execute_migration(<that SQL>, phase='expand')`. After
it returns, verify with `table_schema` + `row_count`.

### 12. Delivery — the expand PR
- **PR (default if the github MCP is attached):** push the expand migration
  + dual-write app code to branch `schemaforge/<change-slug>-expand` via the
  github MCP (`create_branch` + `write_file`), open the PR (`open_pull_request`,
  body = safety report + impact mermaid + lock report).
- **Commit-only:** `create_branch` + `write_file` only, no
  `open_pull_request`.
- **Artifact-only:** save `git diff > /workspace/out/diff.patch`.
Follow the user's stated preference exactly; default to PR.

### 13. Qodo review loop (PR delivery only)
After opening the PR, read the review discussions:
`github.get_pull_request(repo, number)`. If review comments exist, fix each
flagged issue in the sandbox, re-verify, and push the fix to the same branch.
Re-check until clean. If the review hasn't landed, tell the user the PR is
open and ask them to say "check the PR review" once it is in.

### 14. Hand off and STOP
Tell the operator explicitly: "Expand applied. Deploy the dual-write app
code from the PR. When deployed and stable, tell me 'contract <change-slug>'
and I will run the contract gate and apply the cleanup." **END THE TURN.**
Do NOT proceed to contract in the same turn.

## Phase 2 — CONTRACT (apply later; gated, destructive)

### 15. Operator triggers contract
The operator says "contract <change-slug>". Fetch the DEPLOYED code fresh —
do NOT scan the locally-modified sandbox checkout (it was edited during
expand authoring): ask the operator which branch they deployed, then
`cd /workspace/app && git fetch origin && git checkout <branch> &&
git reset --hard origin/<branch>`. Then re-run `sf-pipeline facts` and
rebuild the impact graph.

### 16. Contract gate (expected BLOCKED)
```bash
sf-pipeline contract-gate --db out/db.json --code out/code.json --columns <table>.<col>,...
```
It will almost always be `BLOCKED` — the deployed dual-write build still reads
the old columns. That is EXPECTED: it is the signal to author and deploy the
FINAL app (which drops those reads). Proceed to step 17. (Only if it is already
`SAFE` — the operator already deployed a build with no old-column reads — skip
to step 19.)

### 17. Author the FINAL app + CONTRACT migration + verify
Author the FINAL app build (the model reads ONLY the new shape; old columns
removed) and the CONTRACT migration (`<rev>b_<slug>.py`): FIRST a
reconciliation `INSERT..SELECT ... WHERE NOT EXISTS (...)` that backfills the
new table for rows the expand backfill missed (rows created after backfill),
THEN the `drop_*` / `alter_column` cleanup. Then:
```bash
sf-pipeline validate-phase --migration <contract file> --phase contract
```
Must exit 0. Before applying the contract migration in the sandbox, capture
the current revision with `alembic current` (the expand head, e.g. `0002a`)
and store it as `<expand-head>` — step 21's production offline SQL renders
from THIS revision, not the post-apply current (which would be the contract
head and render an empty range). Then verify in the sandbox: apply the
contract migration, run the final tests, parity against the new shape,
EXPLAIN before/after.

### 18. Delivery — the contract PR; END THE TURN
Push the final app + contract migration to branch
`schemaforge/<change-slug>-contract`, open the PR (body = contract safety
report + gate verdict), and run the Qodo review loop (step 13). Tell the
operator explicitly: "Contract PR opened. Deploy the FINAL app from this PR.
When deployed and stable, tell me 'apply contract <change-slug>' and I will
re-run the gate and apply the cleanup DDL." END THE TURN. Do NOT apply the
DDL yet.

### 19. Operator confirms the final app is deployed — re-run the gate
Re-run `sf-pipeline facts` on the now-deployed code. Fetch it fresh first
(`cd /workspace/app && git fetch origin && git reset --hard origin/<branch>`
— ask the operator for the deployed final branch), then re-run the contract
gate. It MUST be `SAFE` (no deployed code reads the old columns). If still
`BLOCKED`: list every blocker and STOP — the operator has not deployed the
final build yet.

### 20. Present contract report and PAUSE
Present the contract safety report + the `SAFE` gate verdict and call
`ask_user_question` — Approve / Deny.

### 21. On approval — production apply (contract)
`alembic upgrade <expand-head>:head --sql > /workspace/out/contract.sql` (the
`<expand-head>` captured in step 17 — NOT the post-apply current, which would
render an empty range), then `postgres-prod.execute_migration(<that SQL>)`
(phase defaults to full — contract contains the drops). Verify `table_schema`
+ `row_count`.

## Output contract
- End every phase with one status line + artifact paths.
- Impact graph: mermaid code block in chat AND saved to `out/graph.mmd`.
- Safety report: markdown; every number must come from a tool result or the
  engine; label estimates as estimates.
- The contract-gate verdict (SAFE/BLOCKED + blockers) is part of the
  contract report — never omit it.
- If a step fails twice, stop and report the failure with the exact error —
  do not improvise around safety invariants.
