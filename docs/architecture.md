# SchemaForge Architecture

> **Version:** 0.1 — Bootstrap skeleton
> **Status:** Pipeline interface defined; agent implementations pending.

---

## Overview

SchemaForge is an AI-powered **schema migration and code transformation platform**.

It analyses the full impact of a database schema change — across the database itself, application code, ORM models, DAOs, services, and tests — then generates a safe, reviewable migration plan and coordinates execution behind a human-approval gate.

The analysis pipeline is powered by **TrueForge**, Google's agent orchestration framework. Each pipeline stage runs as a TrueForge agent that can call tools (MCP servers, static analysers, sandboxes) to gather evidence before producing a typed artefact.

---

## End-to-End Pipeline

```
User Request
     │
     ▼
┌─────────────────────────┐
│  1. Migration Request   │  User describes the desired schema change.
│     (MigrationRequest)  │  Validated against a Zod schema at the boundary.
└─────────────┬───────────┘
              │
     ┌────────┴────────┐
     ▼                 ▼
┌──────────────┐  ┌──────────────┐
│ 2. DB        │  │ 3. AST       │  Run concurrently (independent data sources).
│    Analysis  │  │    Analysis  │
│              │  │              │
│ TrueForge    │  │ TrueForge    │
│ DB Analyser  │  │ AST Analyser │
│              │  │              │
│ Output:      │  │ Output:      │
│ Database     │  │ ASTFindings  │
│ Findings     │  │              │
└──────┬───────┘  └──────┬───────┘
       │                 │
       └────────┬────────┘
                ▼
┌─────────────────────────┐
│  4. Impact Graph        │  Merges DB + AST findings into a unified
│     (ImpactGraph)       │  dependency graph of affected nodes:
│                         │    tables → columns → files → services → tests
│  TrueForge              │
│  Impact Graph Builder   │
└─────────────┬───────────┘
              │
              ▼
┌─────────────────────────┐
│  5. Migration Plan      │  Ordered list of migration steps:
│     (MigrationPlan)     │    - Schema DDL (CREATE, ALTER, DROP)
│                         │    - Data backfill
│  TrueForge              │    - Code changes (ORM, DAO, service, tests)
│  Plan Generator         │    - Rollback DDL
└─────────────┬───────────┘
              │
              ▼
┌─────────────────────────┐
│  6. Code Refactor       │  Applies code changes from the plan to the
│     (NOT YET IMPL.)     │  codebase: ORM models, DAOs, services, tests.
│                         │
│  TrueForge              │
│  Code Refactor Agent    │
└─────────────┬───────────┘
              │
              ▼
┌─────────────────────────┐
│  7. Sandbox Execution   │  Runs the migration + tests in an isolated
│     (NOT YET IMPL.)     │  sandbox environment to catch regressions
│                         │  before touching production.
│  TrueForge              │
│  Sandbox Runner         │
└─────────────┬───────────┘
              │
              ▼
┌─────────────────────────┐
│  8. Safety Report       │  Aggregates sandbox results, FK checks,
│     (SafetyReport)      │  data-loss risk, rollback feasibility.
│                         │
│  TrueForge              │
│  Safety Checker         │
└─────────────┬───────────┘
              │
              ▼
┌─────────────────────────┐
│  9. Human Approval      │  Blocking gate. A human reviews the plan
│     (ApprovalState)     │  and safety report before production execution.
│     (NOT YET IMPL.)     │
└─────────────┬───────────┘
              │
              ▼
┌─────────────────────────┐
│ 10. Production          │  Applies the approved plan to production:
│     (NOT YET IMPL.)     │    - Runs schema DDL
│                         │    - Backfills data
│                         │    - Deploys code changes
└─────────────────────────┘
```

---

## Module Map

```
src/
├── main.ts                     Entry point / bootstrap
├── config.ts                   Environment configuration
├── logger.ts                   Structured logger
├── errors.ts                   Typed error hierarchy
├── orchestrator.ts             Pipeline coordination
├── types/
│   └── index.ts                All shared Zod-validated domain types
└── integrations/
    └── trueforge.ts            TrueForge adapter interface + stub
```

---

## Typed Pipeline Artefacts

Each stage produces a typed artefact validated with Zod:

| Stage | Input | Output type |
|---|---|---|
| 1 | User intent | `MigrationRequest` |
| 2 | Request | `DatabaseFindings` |
| 3 | Request + DB findings | `ASTFindings` |
| 4 | DB + AST findings | `ImpactGraph` |
| 5 | Impact graph | `MigrationPlan` |
| 6 | Plan | Code diffs (not yet typed) |
| 7 | Code diffs | Sandbox results (not yet typed) |
| 8 | All above | `SafetyReport` |
| 9 | Safety report | `ApprovalState` |
| 10 | Approved plan | Production execution log (not yet typed) |

---

## TrueForge Integration

Each pipeline stage that requires AI or external tool access is implemented as a **TrueForge agent**. SchemaForge communicates with TrueForge via the `ITrueForgeAdapter` interface ([`src/integrations/trueforge.ts`](../src/integrations/trueforge.ts)).

In this version the `StubTrueForgeAdapter` is used, which throws `NotImplementedError` for every method. The interface contract is fully defined, ready for concrete agent implementations.

---

## Design Principles

1. **Typed boundaries everywhere** — all inter-stage data is validated with Zod at parse time.
2. **Honest stubs** — unimplemented features throw `NotImplementedError`, never silently succeed.
3. **Human-in-the-loop** — production execution is blocked behind an explicit human approval gate.
4. **No secrets in code** — all credentials flow through environment variables only.
5. **Minimal dependencies** — only `zod` and `dotenv` in production dependencies.
