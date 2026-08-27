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