# SchemaForge — Hackathon Submission Write-up

**Track:** Best Use of TrueForge (Double-O)
**Repo:** https://github.com/ronakgupta03/schemaforge
**Video:** (link added after recording)

---

## What the agent does

SchemaForge is an autonomous database-migration agent: you ask for a schema
change in plain language ("Split the users table into users and
user_profiles…"), and it delivers the coordinated database **and**
application-code change — impact graph first, then a data-preserving
Alembic migration plus the refactored ORM/endpoints, proven safe in an
isolated sandbox, applied to production only behind a human approval gate,
and finally opened as a GitHub pull request. The analysis is deterministic:
a `schemaforge_core` engine parses the codebase with the Python `ast`
module and introspects Postgres via `information_schema`/`pg_catalog`, so
the impact graph (26 nodes, 43 edges in the demo: tables → ORM models →
attributes → endpoints → raw SQL) is computed, not guessed. The LLM plans,
orchestrates, and explains over that graph. In the live run the agent
authored the migration itself (expand → backfill → contract, with its own
data-parity guard), ran the full verification suite (migration PASS, six
application contract tests PASS, data parity PASS), measured DDL wall time
(1,052 ms on 100k rows), and reported the rollback plan before asking for
approval.

## How it uses TrueForge

**Real tools via MCP.** Two in-repo MCP servers are attached to the agent:
`postgres-prod` (list_tables, table_schema, row_count, EXPLAIN — plus the
two approval-gated write tools) and `github` (get_repo, create_branch,
write_file, open_pull_request). The root agent delegates DB introspection
to one subagent and code analysis to another; both drive the MCP servers
and the sandbox in parallel, and only their final results return to the
root — the demo shows `thread.created` twice and the tool calls scrolling.

**Sandbox Code Mode.** The Daytona sandbox is provisioned on demand and
used for everything risky: the repo is cloned into `/workspace`, Postgres
is installed and seeded (100k users / 1k books), the engine's `sf-pipeline`
CLI runs (snapshot, facts, graph, impact, verify, bench), the agent authors
and tests the migration there, and only the **offline SQL** of the verified
migration is ever passed to the production database. Model credentials
never enter the sandbox.

**Subagents.** Two parallel subagents (db-analysis, code-analysis) do the
legwork with bounded context; the root merges their JSON results into the
impact graph and owns all user interaction.

**Approval gate.** The only production write path is
`postgres-prod.execute_migration` / `execute_ddl`, annotated
`destructiveHint` so TrueForge pauses the turn. The demo's money shot is
the chat freezing on the approval card — the migration is fully verified
and the SQL is ready, but nothing touches prod until a human clicks
**Approve**. The apply runs in one transaction: any failure rolls back to
zero partial state, and backfills are restricted to tables created by the
migration (no data duplication). Reversible actions (branch/PR creation)
carry no approval requirement, keeping the single irreversible moment
exactly where it belongs.

**Session persistence.** The demo includes a server restart mid-session:
the session, turn history, and pending state survive (SQLite local mode),
and a follow-up turn chains cleanly — the "session holding together across
reconnects" property from the hackathon brief, exercised live.

**Qodo gate.** Every substantive change in the repo went through a
Qodo-reviewed pull request — including the PR the agent itself opened,
which Qodo flagged for a rollback edge case ("Profileless users block
rollback") that the agent's downgrade guard fixed. Evidence in the README.

---

*Submitted for the Agent Harness Hackathon, Aug 2026.*