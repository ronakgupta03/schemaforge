---
name: schemaforge-migration
description: Run the SchemaForge migration workflow — snapshot, impact graph, migration authoring, sandbox verification, safety report, approval-gated production DDL, and the follow-up PR. Use for any requested database schema change.
---

# SchemaForge migration workflow

## When to use
Any user request to change the Postgres schema of `demo-app`
(add/split/drop/rename columns or tables).

## Invariants
1. Production is never written except via `postgres-prod.execute_migration`
   (full batches) or `postgres-prod.execute_ddl` (pure DDL), which the
   harness pauses for human approval.
2. All analysis is deterministic: `schemaforge_core` (sandbox) — never
   eyeballed parsing.
3. Tests in `demo-app/tests/` are the API contract; never edit them.
5. The revision's `downgrade()` MUST ship the orphan-guard DO block:
   `DO $$ BEGIN IF EXISTS (SELECT 1 FROM users u WHERE NOT EXISTS
   (SELECT 1 FROM user_profiles p WHERE p.user_id = u.id)) THEN RAISE
   EXCEPTION 'rollback blocked: users exist without a user_profiles row';
   END IF; END $$;` before any `SET NOT NULL` — without it a rollback on
   partial data fails with a cryptic `IntegrityError` (Qodo finding on the
   agent-authored PR #15; do not regress it).
6. The pre-approval flow must fit inside the server's execution window
   (default 600 s): no DDL timing / re-seeding / re-verifying before the
   approval pause — measure DDL wall time only after approval.

## Steps
1. Sandbox bootstrap (once per session):
   `git clone --depth 1 https://github.com/ronakgupta03/schemaforge.git /workspace || test -d /workspace/.git`
   then `bash /workspace/scripts/sandbox_setup.sh` — expect `SANDBOX_READY`.
   After bootstrap, `source /workspace/.sfenv-activate.sh` in every shell so
   `python`/`alembic`/`pytest` resolve to the venv. If the clone fails with
   permission denied on `/workspace`, run
   `sudo chown -R daytona:daytona /workspace` first.
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
5. Baseline: `sf-pipeline snapshot --dsn $DATABASE_URL --out out/db_before.json`
   and `sf-pipeline bench --dsn $DATABASE_URL --queries demo-app/queries/bench.sql --out out/explain_before.json`
   (run against the SANDBOX dsn — the sandbox DB mirrors prod's pre-migration state).
6. Author the migration in `/workspace/demo-app`: new alembic revision
   (0002) + code edits. Write a parity SQL file for THIS change.
8. Present `out/report.md` in chat and PAUSE: call `ask_user_question`
   with options Approve / Deny / Request changes — do not end the turn
   silently after the report. Wait for the user's answer.
9. On approval: `cd demo-app && alembic upgrade 0001:head --sql` (sandbox;
   `0001:head` applies only the new revision — prod is already at 0001) →
   `postgres-prod.execute_migration(<that SQL>)`. After it returns, measure
   the DDL wall time (for the report's lock estimate: time the upgrade with
   `time.perf_counter()` in a Code Mode script; report "DDL took X ms on
   100k rows (sandbox)") and verify with `table_schema` + `row_count`.
10. PR: github MCP → push modified files to branch `schemaforge/<slug>` →
    create PR (body = safety report + impact mermaid).
8. Measure DDL wall time in the sandbox (for the report's lock estimate):
   time the `alembic upgrade head` on a re-seeded copy, or wrap the DDL
   statements with `time.perf_counter()` in a Code Mode script; report
   "DDL took X ms on 100k rows (sandbox)".
9. Present `out/report.md` in chat and STOP — wait for the user's approval.
10. On approval: `cd demo-app && alembic upgrade 0001:head --sql` (sandbox;
    `0001:head` applies only the new revision — prod is already at 0001) →
    `postgres-prod.execute_migration(<that SQL>)`. Verify with `table_schema`
    + `row_count` after it returns.
11. PR: github MCP → push modified files to branch `schemaforge/<slug>` →
    create PR (body = safety report + impact mermaid).