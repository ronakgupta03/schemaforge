# SchemaForge

**AI-powered schema migration and code transformation platform.**

SchemaForge analyses the full blast-radius of a database schema change — across the live database, ORM models, DAOs, services, and tests — then generates a safe, step-by-step migration plan and coordinates execution behind a human-approval gate.

---

## Current Status

> **v0.1 — Bootstrap skeleton**
>
> The project structure, shared types, pipeline orchestrator, and TrueForge integration interface are in place.
> No agent implementations are connected yet — all analysis stages surface `NotImplementedError`.

| Feature | Status |
|---|---|
| Project structure & config | ✅ Done |
| Shared domain types (Zod) | ✅ Done |
| Pipeline orchestrator skeleton | ✅ Done |
| TrueForge adapter interface | ✅ Done |
| Structured logger | ✅ Done |
| Typed error hierarchy | ✅ Done |
| `examples/users-split` fixture | ✅ Done |
| Smoke tests | ✅ Done |
| DB analysis (TrueForge agent) | ⏳ Not yet implemented |
| AST analysis (TrueForge agent) | ⏳ Not yet implemented |
| Impact graph builder | ⏳ Not yet implemented |
| Migration plan generator | ⏳ Not yet implemented |
| Code refactor agent | ⏳ Not yet implemented |
| Sandbox execution | ⏳ Not yet implemented |
| Safety report | ⏳ Not yet implemented |
| Human approval gate | ⏳ Not yet implemented |
| Production execution | ⏳ Not yet implemented |

---

## Architecture

```
User Request
     │
     ├─► DB Analysis ──────────┐
     └─► AST Analysis ─────────┤
                               ▼
                         Impact Graph
                               │
                               ▼
                        Migration Plan
                               │
                               ▼
                        Code Refactor  (⏳)
                               │
                               ▼
                       Sandbox Execution (⏳)
                               │
                               ▼
                        Safety Report
                               │
                               ▼
                      Human Approval Gate (⏳)
                               │
                               ▼
                           Production (⏳)
```

See [`docs/architecture.md`](docs/architecture.md) for the full pipeline description, module map, and design principles.

---

## Local Setup

### Prerequisites

- Node.js ≥ 20
- npm ≥ 10

### Install

```bash
git clone <repo>
cd schemaforge
pnpm install
```

### Environment

```bash
cp .env.example .env
# Edit .env – see .env.example for all supported variables
```

### Run (skeleton dry-run)

```bash
pnpm run dev
```

This runs the orchestrator in **dry-run mode** — it validates a sample `MigrationRequest` and logs the result. No database or LLM connection is required.

Expected output (development mode):

```
[...] INFO  SchemaForge starting { env: 'development', ... }
[...] INFO  Migration request created { requestId: '...', type: 'split_table' }
[...] INFO  Dry-run: pipeline validated (no agent calls made) { ... }
[...] INFO  Dry-run complete { ..., reachedStage: 'request_received', approvalStatus: 'pending' }
[...] INFO  SchemaForge skeleton is operational. Connect TrueForge adapters to enable the full analysis pipeline.
```

### Build

```bash
pnpm run build        # Compile TypeScript to dist/
pnpm typecheck        # Type-check without emitting
```

### Test

```bash
pnpm test             # Run all tests
pnpm run test:coverage
```

### Lint

```bash
pnpm run lint
pnpm run lint:fix
```

---

## Project Structure

```
schemaforge/
├── src/
│   ├── main.ts                  Application entry point
│   ├── config.ts                Environment configuration
│   ├── logger.ts                Structured logger
│   ├── errors.ts                Typed error hierarchy
│   ├── orchestrator.ts          Pipeline orchestrator
│   ├── types/
│   │   └── index.ts             All shared Zod domain types
│   └── integrations/
│       └── trueforge.ts         TrueForge adapter interface + stub
├── tests/
│   └── smoke/
│       ├── types.test.ts        Type validation smoke tests
│       └── orchestrator.test.ts Orchestrator smoke tests
├── examples/
│   └── users-split/             Deterministic fixture for the users-split migration
│       ├── schema.sql
│       ├── models/user.ts
│       ├── dao/user-dao.ts
│       ├── services/user-service.ts
│       └── tests/user-split.test.ts
├── docs/
│   └── architecture.md          Full architecture documentation
├── package.json
├── pnpm-lock.yaml
├── tsconfig.json
├── jest.config.ts
└── .eslintrc.json
```

---

## Contributing

This project follows the hackathon PR workflow:

1. Work on a feature branch.
2. Run tests: `pnpm test`.
3. Commit logically separated changes.
4. Push and open a GitHub PR.
5. Qodo reviews the PR.
6. Fix High-severity findings.
7. Re-push → re-review.
8. Merge manually after approval.

Do **not** push substantive changes directly to `main`.
