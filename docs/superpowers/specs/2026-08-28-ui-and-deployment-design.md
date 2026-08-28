# SchemaForge UI + Cloudflare Deployment — Design

Date: 2026-08-28
Status: Approved (brainstorming, 2026-08-28)
Hackathon: WeMakeDevs Agent Harness Hackathon — Best UI track + optional "Deployed link to project" field

## Goal

Build a product-grade web UI for the SchemaForge agent that puts the **evidence on screen before every approval** — and deploy the full stack (frontend + backend) to Cloudflare so the submission's optional "deployed link" field points at the real working product.

### Problem being solved

The current UI is TrueForge's built-in chat (localhost:8790). Live-verified (Task 12.7): it renders markdown natively but the three "money shot" artifacts — the mermaid impact graph, the safety report body, and approval/tool-call cards — are not rendered inline. A user is asked to approve a production migration while only seeing file references (`graph.mmd`, `report.md`). **No blind approval** is the product thesis of this UI.

### Non-goals

- Not rebuilding chat from scratch (Option A rejected): the TrueForge UI SDK owns conversation, streaming, session history, and approval cards.
- Not a static showcase/landing page as the deployed link (fallback only).
- No changes to the agent's core behavior; no new backend beyond what TrueForge already exposes.
- No multi-tenant support, auth system, or admin surface — single-demo-runner scope.

## Decisions (with rationale)

| Decision | Choice | Why |
|---|---|---|
| UI role | **Product (a)**: judge types the split prompt and watches everything render live | Only a real product competes for a UI award on an agent hackathon; doubles as the demo-video surface |
| Build approach | **Option B**: TrueForge UI SDK (`@truefoundry/trueforge-ui`) for chat + custom React evidence panels | SDK handles the hard chat plumbing; the differentiated part (artifact rendering) is ours either way; using the sponsor SDK also scores "use of sponsor tools" |
| Mandatory evidence | **All 5**: impact graph, safety report, changes (SQL + diff), verification detail, sandbox activity | Chosen by user; 1+2+3 answer "what will change" and "is it safe", 4 folds into the report card, 5 is a compact activity rail |
| Hosting | **Cloudflare**: Pages (UI) + Worker proxy + Containers (backend services) + Neon (Postgres) + Workers AI (model) | User has Workers Paid plan + Cloudflare resources. Containers GA (2026-04-13) runs arbitrary Docker images; the only hard constraint is ephemeral container disk, so Postgres lives in Neon |
| Postgres | **Neon**, two DBs: `trueforge` (harness metadata) + `bookstore` (prod migration target) | CF Containers disk is ephemeral by design; R2-FUSE is documented as non-SSD performance — not acceptable for Postgres |

## Architecture

### In-browser (one page)

```
┌────────────────────────── Browser (one page) ──────────────────────────┐
│ TrueForge UI SDK (chat: streaming, history, approval cards)            │
│ + SchemaForge Evidence Panel (our code): 5 tabs, live-updating         │
│ + thin data layer: sfApi — sessions / events / sandbox-file downloads  │
└─────────────┬────────────────────────────────▲─────────────────────────┘
              │ chat via SDK (SDK manages its  │ poll artifacts (graph.mmd,
              │ own sessions/turns)            │ report.md, verify.json, …)
              ▼                                │
        TrueForge server ──► Daytona sandbox ──► /workspace/out/*
```

- The SDK owns conversation, streaming, session history, and approval/resume cards.
- Our code only renders evidence. Panels pull artifacts from the TrueForge API: session-scoped `download-sandbox-file` and turn `events`. No new backend surface; no fake data path.

### Deployed topology (Cloudflare)

```
judge's browser
      │  https://<project>.pages.dev
      ▼
┌─ Cloudflare Pages: Vite/React UI (SDK chat + evidence panels) ──┐
│  /api/*  ─► Worker proxy (adds CORS; /mcp not exposed)          │
└───────────────────────────┬──────────────────────────────────────┘
                            ▼
┌────────── CF Containers (one wrangler project) ──────────────────┐
│  trueforge-server   :8791  hosted mode, keep-alive               │
│  postgres-mcp       :8001  keep-alive                            │
│  github-mcp         :8002  keep-alive                            │
│  redis              :6379  ephemeral disk acceptable, keep-alive │
└──────┬──────────────────────────┬────────────────────────────────┘
       │ Postgres (metadata/sessions)          │ Daytona sandbox (external API)
       ▼                                       │ Workers AI (model, already used)
   Neon db `trueforge`                         └── secrets via wrangler secrets
   Neon db `bookstore` (prod target, seeded 200k users / 5k books)
```

## Components

### 1. UI app (`ui/` — new Vite/React project)

- **Chat column (~55%)**: `<TrueForgeUI>` with `layout="sidebar"` (full-page layout with persistent thread list) filling the left column; agentConfig pinned to the `schemaforge` agent; custom `SemanticTokens` theme (dark, migration-tool aesthetic) shared with the evidence panel CSS.
- **Evidence panel (~45%)**: tabbed — Impact | Report | Changes | Verification | Activity.
- **Data layer (`sfApi`)**: thin TS module —
  - `activeSession()`: latest active session for the `schemaforge` agent (GET `/api/v1/sessions`, pick newest by `updated_at`). Used as the polling context. Rationale: the SDK does not guarantee an exposed session id; single-runner demo makes "latest active session" a safe heuristic.
  - `pollArtifacts(sessionId)`: download `out/graph.mmd`, `out/report.md`, `out/verify.json`, `out/migration.sql`, `out/diff.patch` via the session-scoped sandbox-file endpoint; retry while the turn is running (files appear progressively).
  - `activityEvents(sessionId)`: turn events filtered to exec/tool activity, grouped by `thread_id`, rendered as a compact timeline.
  - `resume(sessionId, payload)`: posts `user.tool_approval` / `user.tool_response` (fallback path only — see risks).

### 2. The five panels

| # | Panel | Data source | Render |
|---|---|---|---|
| 1 | Impact graph | `out/graph.mmd` | mermaid.js live render |
| 2 | Safety report | `out/report.md` + `out/verify.json` | card: PASS/PASS/PASS badges + DDL wall-time ms |
| 3 | Changes | `out/migration.sql` + `out/diff.patch` | SQL viewer (syntax highlight) + unified diff viewer |
| 4 | Verification | `out/verify.json` | structured rows: parity checks, EXPLAIN before/after timings |
| 5 | Activity | turn events (exec/tool, grouped by thread) | timeline: clone ✓ → snapshot ✓ → verify PASS → Code Mode |

**Approval rule (the product moment):** when a `tool.approval_required` event appears (or the turn pauses), un-reviewed evidence tabs highlight and the panel flashes — *review the proof, then approve*. The SDK renders the approval card; the evidence sits beside it.

### 3. Artifact contract — deterministic agent-side additions

Three stable-path artifacts the agent does not currently save, plus one pipeline tweak:

- `out/verify.json` — **core change (tiny, behavior-neutral)**: `core/schemaforge_core/report.py` already computes checks/parity/bench; add a JSON dump beside the markdown report.
- `out/migration.sql` — **SKILL.md line**: after generating `alembic upgrade 0001:head --sql`, also save it to `out/migration.sql`.
- `out/diff.patch` — **SKILL.md line**: after authoring edits, `git diff > out/diff.patch`.
- Re-run `scripts/apply_agent.py` + `scripts/import_skill.py` (with `.env` sourced) to push the updated instructions/skill to the live agent. Ships via a Qodo-reviewed PR.

## Deployment

### Configuration

- **CF Pages**: build `ui/` on push to main.
- **Containers**: one wrangler project, four container classes; `standard-1` (4 GiB/8 GB disk) for trueforge-server, `lite`/`basic` for MCP servers and redis; sleep disabled by overriding `onActivityExpired` so the stack survives between judges.
- **Worker router**: routes `/api/*` to the trueforge container, adds CORS headers for the Pages origin, passes streaming responses through. MCP servers are NOT exposed publicly (containers talk over internal hostname bindings).
- **TrueForge hosted mode**: Postgres URL → Neon `trueforge`, Redis URL → redis container, `PUBLIC_BASE_URL` = the Pages domain, OIDC left unconfigured (single default admin, same trust model as local mode).
- **Neon**: `trueforge` DB for harness metadata; `bookstore` DB seeded pre-split (200k users / 5k books) via the existing seed flow pointed at the Neon URL. This is the production DB the demo migration applies to.
- **Secrets** (wrangler secrets, never in repo): DAYTONA_API_KEY, CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_AUTH_TOKEN, GITHUB_PERSONAL_ACCESS_TOKEN, Postgres credentials.
- **Model**: Workers AI `deepseek-v4-flash` (already registered as the `cloudflare` custom provider).

- **TrueForge hosted mode**: Postgres URL → Neon `trueforge`, Redis URL → redis container, `PUBLIC_BASE_URL` = the Pages domain, OIDC left unconfigured initially — assumed to behave like local mode's single shared admin identity (same trust model), to be verified in build-order step 4 before wiring the demo flow.

1. **UI locally** — Vite app against local TrueForge (vite proxy solves dev CORS). Demo video can be filmed against this even if deploy slips.
2. **Frontend deploy** — CF Pages. Zero risk to the demo.
3. **Neon setup** — two DBs; seed `bookstore` 200k/5k.
4. **Containers** — trueforge + redis + 2 MCP servers, hosted-mode env, keep-alive.
5. **Worker router + secrets** — wire `/api/*`; verify SSE end-to-end from the Pages origin.
6. **Judge-flow smoke on the deployed URL** — create session, run the locked split prompt, watch all 5 panels fill, approve, verify parity 200k=200k.

### Fallback ladder

| If this fails | Do this |
|---|---|
| SSE through Worker→Container misbehaves | Panels/chat fall back to event polling (existing pollers are proven) |
| Container keep-alive or cold-start friction | Accept 1–3 s first-request wake; verify sleep override works |
| Hosted-mode TrueForge config fights back | Deploy the UI to Pages anyway; deployed link = UI + video exhibit, demo stays local |
| SDK cannot render `ask_user_question` pauses | Evidence panel renders the question card and posts `user.tool_response` via sfApi (fallback path) |

## Risks

| Risk | Mitigation |
|---|---|
| CORS / cross-origin SDK + panel fetches | Worker proxy layer; vite proxy in dev |
| SDK internals don't expose session id | `activeSession()` latest-active-session heuristic (single-runner demo) |
| SSE through Worker→Container unverified | Polling fallback (proven in Task 12) |
| Containers are Workers-Paid-plan only; cold starts 1–3 s | User confirmed Paid plan; sleep override + warm keep-alive |
| Hosted-mode TrueForge never run before (PUBLIC_BASE_URL, Postgres/Redis wiring) | Build order puts it last; fallback ladder keeps the submission safe |
| ~2-day window; demo video is mandatory | UI is local-first; video filmed against local or deployed, whichever passes first |

## Testing / acceptance

- **Local**: full flow against localhost via vite proxy; acceptance: all 5 panels populate **before** the approval card appears.
- **Deployed**: one full judge-flow run mirroring Task 12 acceptance — verify PASS, approval pause renders with evidence, apply, parity 200k=200k.
- **Demo video**: filmed against the deployed URL if the smoke passes; otherwise local UI (identical code).

## Repo impact

- `ui/` — new Vite/React app (SDK + panels + sfApi).
- `ui` wrangler config — containers + router Worker.
- `core/schemaforge_core/report.py` — add `verify.json` dump (behavior-neutral).
- `skills/schemaforge-migration/SKILL.md` — two artifact-save lines.
- `README.md` — "Deployed" section + UI quickstart.
- Everything through Qodo-reviewed PRs; none of it touches the agent's core behavior.

## Out of scope

- Auth/multi-user, custom domain (pages.dev subdomain is sufficient), CI/CD beyond Pages builds, replacement of the local demo flow (local remains the fallback), any new backend service.