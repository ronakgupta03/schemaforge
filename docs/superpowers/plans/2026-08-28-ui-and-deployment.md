# SchemaForge Evidence UI + Cloudflare Deployment — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an evidence-first web UI for the SchemaForge agent (chat + five live artifact panels, no blind approvals) and deploy the full stack to Cloudflare (Pages + Containers + Neon), producing the submission's "deployed link".

**Architecture:** A Vite/React single page embeds the TrueForge UI SDK (`@truefoundry/trueforge-ui`) in the left column for chat/streaming/approvals; our own right-column Evidence Panel polls the TrueForge API (sessions → turns → events → sandbox-file downloads) and renders the impact graph (mermaid), safety report, migration SQL + code diff, verification details, and sandbox activity. Everything is same-origin: dev uses a vite proxy to the local harness (`[::1]:8790`); production uses Cloudflare Pages with a Pages Function router that forwards `/api/*` to TrueForge running in a CF Container. Postgres lives in Neon (CF Container disk is ephemeral); Redis runs as a container. The agent gains a deterministic artifact contract (`out/verify.json`, `out/migration.sql`, `out/diff.patch`) so the panels always know where to look.

**Tech Stack:** Vite 6 + React 18 + TypeScript; `@truefoundry/trueforge-ui@0.2.4` (+ peer `@assistant-ui/core@^0.2.22`, `@assistant-ui/react@^0.14.24` as direct deps — dedupe trap); `mermaid`, `react-markdown`, `react-syntax-highlighter`; vitest + @testing-library/react; wrangler (installed globally) + `@cloudflare/containers`; Neon Postgres; Workers AI (existing).

## Global Constraints

- **Repo:** `/home/utsav/Github/schemaforge`, default branch `main`. Every substantive change ships as a Qodo-reviewed PR — next number **#18**. Docs-only commits may go straight to main.
- **User-owned services:** the local TrueForge (`[::1]:8790`), both MCP servers, and prod Postgres (`:5433`) are the user's running processes — never restart, kill, or adopt them.
- **Local-mode IPv6:** TrueForge binds only `[::1]:8790`, never `127.0.0.1`. All dev proxy targets must use `http://[::1]:8790`.
- **Same-origin rule:** the UI never fetches an absolute URL; everything is relative `/api/...` (vite proxy in dev, Pages Function in prod).
- **SDK peer deps:** `@assistant-ui/core` and `@assistant-ui/react` must be direct dependencies AND `resolve.dedupe`'d, or the UI throws `requires an AuiProvider`.
- **Model:** `cloudflare/deepseek-v4-flash`; token budget for a full live turn is ~120-300k input — long runs may hit transient 429s; retry, never redesign.
- **Qodo gate:** PRs #18 (UI), #19 (artifact contract), #20 (deploy). Branches `feat/evidence-ui`, `feat/artifact-contract`, `feat/cf-deploy`. No direct pushes to main for code.
- **Verify before claiming:** every acceptance in this plan is an observable command result or a browser observation, not an assertion.
- **Demo video is mandatory and must not be blocked by this work.** Build order below keeps the demo filmable at each milestone (local UI works without any deploy step).
- The `schemaforge` agent name is immutable: `schemaforge`. Sessions list exposes `agent.name`; turn events expose `thread_id` (`main` = root, generated = subagent).

---

## File Structure

```
ui/                                  # NEW — the product UI
├── package.json                     # deps pinned per Global Constraints
├── vite.config.ts                   # react plugin, /api proxy → [::1]:8790, dedupe
├── tsconfig.json                    # standard vite react-ts
├── index.html
├── src/
│   ├── main.tsx                     # mount <App/>; import styles.css
│   ├── App.tsx                      # h-dvh layout: SDK chat (55%) + EvidencePanel (45%)
│   ├── styles.css                   # @import "tailwindcss" + SDK styles + theme vars
│   ├── sfApi.ts                     # fetch-based API client (injectable fetch)
│   ├── verify.ts                    # VerifyJson guard + badge mapping (pure)
│   ├── diff.ts                      # unified-diff line parser (pure)
│   ├── hooks/useEvidence.ts         # polling state machine (sessions/turns/events/artifacts)
│   └── components/
│       ├── EvidencePanel.tsx        # tabs + approval-glow + visited tracking
│       ├── ImpactGraph.tsx          # mermaid render
│       ├── SafetyReport.tsx         # PASS/PASS/PASS badges + report.md body
│       ├── ChangesPanel.tsx         # migration.sql + diff.patch viewers
│       ├── VerificationPanel.tsx    # verify.json structured rows
│       └── ActivityPanel.tsx        # event timeline grouped by thread
deploy/                              # NEW — Cloudflare stack
├── wrangler.toml                    # Pages project + 4 container classes + bindings
├── functions/api/[[path]].js        # Pages Function: /api/* → TrueForge container
├── Dockerfile.trueforge             # node:22-bookworm-slim + @truefoundry/trueforge
├── Dockerfile.postgres-mcp          # python:3.12-slim + mcp-server deps
├── Dockerfile.github-mcp            # python:3.12-slim + github-mcp deps
core/schemaforge_core/report.py      # MODIFY: add render_json() (Task 7)
core/schemaforge_core/pipeline.py    # MODIFY: cmd_verify writes verify.json (Task 7)
core/tests/test_report.py            # MODIFY: render_json shape test (Task 7)
skills/schemaforge-migration/SKILL.md# MODIFY: artifact-save lines + dup-steps cleanup (Task 7)
README.md                            # MODIFY: Deployed section (Task 10)
```

**Milestones:** PR #18 = Tasks 1-6 (UI, fully working against local harness). PR #19 = Task 7 (artifact contract). PR #20 = Tasks 8-10 (deploy + README).

---

## Task 1: UI scaffold — SDK chat in a shell

**Files:**
- Create: `ui/package.json`, `ui/vite.config.ts`, `ui/tsconfig.json`, `ui/index.html`, `ui/src/main.tsx`, `ui/src/App.tsx`, `ui/src/styles.css`
- Test: none (scaffold; verified by dev-server render)

**Interfaces:**
- Produces: `App.tsx` renders `<TrueForgeUI>` with `server`, `agentConfig`, `theme`; the EvidencePanel slot (rendered as a placeholder in this task) is filled by Task 4/5.

- [ ] **Step 1: Scaffold the Vite project**

Run:
```bash
cd /home/utsav/Github/schemaforge && git checkout -b feat/evidence-ui
npm create vite@latest ui -- --template react-ts
cd ui && npm install
npm install @truefoundry/trueforge-ui@0.2.4 @assistant-ui/core@^0.2.22 @assistant-ui/react@^0.14.24 mermaid react-markdown react-syntax-highlighter
npm install -D vitest @testing-library/react @testing-library/jest-dom jsdom
```
Expected: `ui/` created, `npm install` clean, `@truefoundry/trueforge-ui@0.2.4` in `package.json` dependencies (no `^`).

- [ ] **Step 2: Verify the SDK export surface**

Run:
```bash
grep -o "createTrueFoundryServer" node_modules/@truefoundry/trueforge-ui/dist/index.js | head -1
```
Expected: prints `createTrueFoundryServer`.
If the grep is empty, the factory lives in `@truefoundry/assistant-ui-runtime` — import from there instead. Note the choice in `ui/src/App.tsx` as a comment.

- [ ] **Step 3: Write vite.config.ts**

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  resolve: {
    dedupe: ["@assistant-ui/core", "@assistant-ui/react", "react", "react-dom"],
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: "http://[::1]:8790", changeOrigin: false },
    },
  },
});
```
Note: `[::1]` is deliberate — the local harness binds IPv6 loopback only (Global Constraint).

- [ ] **Step 4: Write src/styles.css**

```css
@import "tailwindcss";
@import "@truefoundry/trueforge-ui/styles.css";

:root {
  --sf-bg: #0b1220;
  --sf-panel: #101a2e;
  --sf-border: #1e2a44;
  --sf-accent: #38bdf8;
  --sf-ok: #34d399;
  --sf-fail: #f87171;
  --sf-text: #e2e8f0;
  --sf-muted: #94a3b8;
}

html, body, #root { height: 100%; }
body { background: var(--sf-bg); color: var(--sf-text); }
```
The `tailwindcss` import resets host styles (the SDK ships without preflight — known requirement).

- [ ] **Step 5: Write index.html**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>SchemaForge — migration agent</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Write src/main.tsx**

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
```

- [ ] **Step 7: Write src/App.tsx**

```tsx
import { TrueForgeUI, createTrueFoundryServer } from "@truefoundry/trueforge-ui";
import { EvidencePanel } from "./components/EvidencePanel";

const server = createTrueFoundryServer({ type: "trueforge", baseUrl: "/" });
const theme = {
  preset: "Custom" as const,
  mode: "dark" as const,
  tokens: {
    primary: "#38bdf8",
    background: "#0b1220",
    foreground: "#e2e8f0",
    muted: "#94a3b8",
    accent: "#818cf8",
    radius: "0.5rem",
  },
};

export default function App() {
  return (
    <div className="flex h-dvh w-full">
      <div className="h-full w-[55%] min-w-0 border-r" style={{ borderColor: "var(--sf-border)" }}>
        <TrueForgeUI
          server={server}
          layout="sidebar"
          agentConfig={{ mode: "SingleAgent", name: "schemaforge" }}
          theme={theme}
          className="h-full"
        />
      </div>
      <div className="h-full flex-1 min-w-0">
        <EvidencePanel />
      </div>
    </div>
  );
}
```
Note: `h-dvh` + `min-w-0` on both columns is required — the SDK collapses to zero height when its parent has no resolved height.

- [ ] **Step 8: Placeholder EvidencePanel**

Create `ui/src/components/EvidencePanel.tsx`:
```tsx
export function EvidencePanel() {
  return (
    <div className="flex h-full items-center justify-center text-sm" style={{ color: "var(--sf-muted)" }}>
      Evidence panel — wired in Tasks 3-5
    </div>
  );
}
```

- [ ] **Step 9: Run the dev server and verify the SDK chat renders**

Run (background):
```bash
cd /home/utsav/Github/schemaforge/ui && npm run dev
```
Then drive a browser to `http://localhost:5173`:
- Expected: dark-themed chat UI renders in the left 55%; the agent library or the `schemaforge` SingleAgent composer is visible; the right column shows the placeholder; no `requires an AuiProvider` error in the console.
- If AuiProvider error: confirm dedupe config (Step 3) and that `@assistant-ui/core` is a direct dep; `npm ls @assistant-ui/core` must show ONE copy.

- [ ] **Step 10: Commit**

```bash
git add ui/
git commit -m "feat(ui): scaffold evidence UI with TrueForge SDK chat shell"
```

---

## Task 2: sfApi — typed client for the TrueForge API

**Files:**
- Create: `ui/src/sfApi.ts`
- Test: `ui/src/sfApi.test.ts`

**Interfaces:**
- Produces: `listSessions(fetchFn): Promise<Session[]>`, `activeSchemaForgeSession(fetchFn): Promise<Session | null>`, `listTurns(fetchFn, sessionId): Promise<Turn[]>`, `listEvents(fetchFn, sessionId, turnId): Promise<ApiEvent[]>`, `downloadArtifact(fetchFn, sessionId, turnId, path): Promise<ArtifactResult>`.
- Every function takes a `fetchFn: typeof fetch` as its first argument — tests inject mocks; the app passes the real `fetch` bound to same-origin relative URLs.

**Live-verified API shapes (ground truth, do not re-derive):**
- `GET /api/v1/sessions` → `{ data: [{ id, agent: {type, id, name}, title, created_at, updated_at }] }`
- `GET /api/v1/sessions/{sid}/turns` → `{ data: [Turn] }` where Turn has `{ id, session_id, previous_turn_id, input, state: { status, reason?, required_actions? }, created_at }`
- `GET /api/v1/sessions/{sid}/turns/{tid}/events` → flat array `[{ type, id, turn_id, thread_id, created_at, ... }]` (NO `{event:...}` wrapper)
- `GET /api/v1/sessions/{sid}/turns/{tid}/download-sandbox-file?path=<abs>` → 200 octet-stream | 404 (not yet) | 410 (sandbox gone) | 412 (no sandbox) | 413 (too large)

- [ ] **Step 1: Write the failing test**

`ui/src/sfApi.test.ts`:
```ts
import { describe, it, expect, vi } from "vitest";
import {
  listSessions, activeSchemaForgeSession, listTurns, listEvents, downloadArtifact,
} from "./sfApi";

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body, text: async () => JSON.stringify(body) } as Response;
}

describe("listSessions", () => {
  it("returns the data array and calls the right path", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ data: [{ id: "s1", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "t", created_at: "", updated_at: "" }] }));
    const sessions = await listSessions(fetch);
    expect(sessions).toHaveLength(1);
    expect(fetch).toHaveBeenCalledWith("/api/v1/sessions");
  });
});

describe("activeSchemaForgeSession", () => {
  it("picks the newest updated_at among schemaforge sessions only", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ data: [
      { id: "old", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "x", created_at: "", updated_at: "2026-08-28T10:00:00Z" },
      { id: "new", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "y", created_at: "", updated_at: "2026-08-28T11:00:00Z" },
      { id: "other", agent: { type: "reference", id: "a2", name: "misc" }, title: "z", created_at: "", updated_at: "2026-08-28T12:00:00Z" },
    ] }));
    expect((await activeSchemaForgeSession(fetch))?.id).toBe("new");
  });
  it("returns null when no schemaforge session exists", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ data: [] }));
    expect(await activeSchemaForgeSession(fetch)).toBeNull();
  });
});

describe("listTurns", () => {
  it("hits the session-scoped turns endpoint", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse({ data: [{ id: "t1" }] }));
    await listTurns(fetch, "s1");
    expect(fetch).toHaveBeenCalledWith("/api/v1/sessions/s1/turns");
  });
});

describe("listEvents", () => {
  it("returns the flat array unchanged", async () => {
    const fetch = vi.fn().mockResolvedValue(jsonResponse([{ type: "tool.response", id: "e1", turn_id: "t1", thread_id: "main" }]));
    const events = await listEvents(fetch, "s1", "t1");
    expect(events[0].type).toBe("tool.response");
    expect(fetch).toHaveBeenCalledWith("/api/v1/sessions/s1/turns/t1/events");
  });
});

describe("downloadArtifact", () => {
  const textResponse = (status: number, text = "") => ({ ok: status < 400, status, text: async () => text, json: async () => ({}) }) as Response;
  it("maps 200 to ok with content", async () => {
    const fetch = vi.fn().mockResolvedValue(textResponse(200, "graph LR"));
    expect(await downloadArtifact(fetch, "s1", "t1", "/workspace/out/graph.mmd"))
      .toEqual({ status: "ok", text: "graph LR" });
  });
  it("maps 404 to pending (file not written yet)", async () => {
    const fetch = vi.fn().mockResolvedValue(textResponse(404));
    expect(await downloadArtifact(fetch, "s1", "t1", "/workspace/out/graph.mmd"))
      .toEqual({ status: "pending" });
  });
  it("maps 410/412 to gone (sandbox destroyed)", async () => {
    for (const status of [410, 412]) {
      const fetch = vi.fn().mockResolvedValue(textResponse(status));
      expect((await downloadArtifact(fetch, "s1", "t1", "/workspace/out/graph.mmd")).status).toBe("gone");
    }
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd ui && npx vitest run src/sfApi.test.ts`
Expected: FAIL — `Cannot find module './sfApi'`.

- [ ] **Step 3: Write the implementation**

`ui/src/sfApi.ts`:
```ts
export interface AgentRef { type: string; id: string; name: string }
export interface Session {
  id: string; agent: AgentRef; title: string; created_at: string; updated_at: string;
}
export interface Turn {
  id: string; session_id: string; previous_turn_id: string | null;
  input: unknown; state: { status: string; reason?: string; required_actions?: unknown[] };
  created_at: string;
}
export interface ApiEvent { type: string; id: string; turn_id: string; thread_id: string | null; created_at?: string; [k: string]: unknown }
export type ArtifactResult =
  | { status: "ok"; text: string }
  | { status: "pending" }
  | { status: "gone" };

type FetchFn = typeof fetch;

async function getJson<T>(fetchFn: FetchFn, path: string): Promise<T> {
  const res = await fetchFn(path);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return (await res.json()) as T;
}

export async function listSessions(fetchFn: FetchFn): Promise<Session[]> {
  const body = await getJson<{ data: Session[] }>(fetchFn, "/api/v1/sessions");
  return body.data ?? [];
}

export async function activeSchemaForgeSession(fetchFn: FetchFn): Promise<Session | null> {
  const sessions = await listSessions(fetchFn);
  const mine = sessions
    .filter((s) => s.agent?.name === "schemaforge")
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return mine[0] ?? null;
}

export async function listTurns(fetchFn: FetchFn, sessionId: string): Promise<Turn[]> {
  const body = await getJson<{ data: Turn[] }>(fetchFn, `/api/v1/sessions/${sessionId}/turns`);
  return body.data ?? [];
}

export async function listEvents(fetchFn: FetchFn, sessionId: string, turnId: string): Promise<ApiEvent[]> {
  return getJson<ApiEvent[]>(fetchFn, `/api/v1/sessions/${sessionId}/turns/${turnId}/events`);
}

export async function downloadArtifact(fetchFn: FetchFn, sessionId: string, turnId: string, path: string): Promise<ArtifactResult> {
  const url = `/api/v1/sessions/${sessionId}/turns/${turnId}/download-sandbox-file?path=${encodeURIComponent(path)}`;
  const res = await fetchFn(url);
  if (res.status === 200) return { status: "ok", text: await res.text() };
  if (res.status === 404) return { status: "pending" };
  if (res.status === 410 || res.status === 412 || res.status === 413) return { status: "gone" };
  throw new Error(`download ${path} -> ${res.status}`);
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `npx vitest run src/sfApi.test.ts`
Expected: PASS, all 7 tests.

- [ ] **Step 5: Commit**

```bash
git add ui/src/sfApi.ts ui/src/sfApi.test.ts
git commit -m "feat(ui): typed TrueForge API client (sfApi)"
```

---

## Task 3: useEvidence — the polling state machine

**Files:**
- Create: `ui/src/hooks/useEvidence.ts`
- Test: `ui/src/hooks/useEvidence.test.tsx`

**Interfaces:**
- Consumes: `sfApi` (`listSessions`, `listTurns`, `listEvents`, `downloadArtifact`), `ARTIFACT_PATHS`.
- Produces: `useEvidence(pollMs = 4000): EvidenceState` where
  `EvidenceState = { session: Session | null; turn: Turn | null; artifacts: Partial<Record<ArtifactKey, string>>; activity: ApiEvent[]; phase: "idle" | "running" | "paused" | "done" | "error"; approvalPending: boolean; loaded: boolean }` and `ArtifactKey = "graph" | "report" | "verify" | "sql" | "diff"`.

**Phase derivation (live-verified):** a paused turn ends with `state.status === "done"` AND a non-empty `state.required_actions`. `approvalPending` = any required action is a tool approval.

- [ ] **Step 1: Write the failing tests**

`ui/src/hooks/useEvidence.test.tsx`:
```tsx
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useEvidence, ARTIFACT_PATHS } from "./useEvidence";
import * as sf from "../sfApi";

const session = { id: "s1", agent: { type: "reference", id: "a1", name: "schemaforge" }, title: "t", created_at: "", updated_at: "2026-08-28T11:00:00Z" };
const runningTurn = { id: "t1", session_id: "s1", previous_turn_id: null, input: {}, state: { status: "running" }, created_at: "" };
const pausedTurn = { ...runningTurn, state: { status: "done", required_actions: [{ type: "tool.approval_required" }] } };

beforeEach(() => { vi.restoreAllMocks(); });

it("polls until artifacts are fetched once each", async () => {
  vi.spyOn(sf, "listSessions").mockResolvedValue([session]);
  vi.spyOn(sf, "listTurns").mockResolvedValue([runningTurn]);
  vi.spyOn(sf, "listEvents").mockResolvedValue([]);
  vi.spyOn(sf, "downloadArtifact").mockImplementation(async (_f, _s, _t, path) =>
    path === ARTIFACT_PATHS.graph ? { status: "ok", text: "graph LR" } : { status: "pending" });

  const { result } = renderHook(() => useEvidence(10));
  await waitFor(() => expect(result.current.loaded).toBe(true));
  expect(result.current.session?.id).toBe("s1");
  expect(result.current.artifacts.graph).toBe("graph LR");
  expect(sf.downloadArtifact).toHaveBeenCalledWith(expect.anything(), "s1", "t1", ARTIFACT_PATHS.graph);
});

it("marks approvalPending when the turn is paused on a tool approval", async () => {
  vi.spyOn(sf, "listSessions").mockResolvedValue([session]);
  vi.spyOn(sf, "listTurns").mockResolvedValue([pausedTurn]);
  vi.spyOn(sf, "listEvents").mockResolvedValue([]);
  vi.spyOn(sf, "downloadArtifact").mockResolvedValue({ status: "pending" });

  const { result } = renderHook(() => useEvidence(10));
  await waitFor(() => expect(result.current.phase).toBe("paused"));
  expect(result.current.approvalPending).toBe(true);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `npx vitest run src/hooks/useEvidence.test.tsx`
Expected: FAIL — `Cannot find module './useEvidence'`.

- [ ] **Step 3: Write the implementation**

`ui/src/hooks/useEvidence.ts`:
```ts
import { useEffect, useRef, useState } from "react";
import { listSessions, listTurns, listEvents, downloadArtifact } from "../sfApi";
import type { Session, Turn, ApiEvent } from "../sfApi";

export type ArtifactKey = "graph" | "report" | "verify" | "sql" | "diff";
export const ARTIFACT_PATHS: Record<ArtifactKey, string> = {
  graph: "/workspace/out/graph.mmd",
  report: "/workspace/out/report.md",
  verify: "/workspace/out/verify.json",
  sql: "/workspace/out/migration.sql",
  diff: "/workspace/out/diff.patch",
};

export interface EvidenceState {
  session: Session | null;
  turn: Turn | null;
  artifacts: Partial<Record<ArtifactKey, string>>;
  activity: ApiEvent[];
  phase: "idle" | "running" | "paused" | "done" | "error";
  approvalPending: boolean;
  loaded: boolean;
}

const EMPTY: EvidenceState = { session: null, turn: null, artifacts: {}, activity: [], phase: "idle", approvalPending: false, loaded: false };

function derive(turn: Turn | null, approvalPending: boolean): EvidenceState["phase"] {
  if (!turn) return "idle";
  const s = turn.state?.status;
  if (s === "done") return approvalPending ? "paused" : "done";
  if (s === "cancelled" || s === "error") return "error";
  return "running";
}

export function useEvidence(pollMs = 4000): EvidenceState {
  const [state, setState] = useState<EvidenceState>(EMPTY);
  const fetchedArtifacts = useRef<Partial<Record<ArtifactKey, boolean>>>({});
  const seenEvents = useRef<Set<string>>(new Set());

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;

    async function tick() {
      try {
        const session = await activeSession();
        if (!session) {
          if (!cancelled) setState((s) => ({ ...s, loaded: true }));
          schedule(); return;
        }
        const turns = await listTurns(fetch, session.id);
        const turn = turns[0] ?? null;

        let approvalPending = false;
        const freshEvents: ApiEvent[] = [];
        if (turn) {
          const events = await listEvents(fetch, session.id, turn.id);
          for (const e of events) {
            if (!seenEvents.current.has(e.id)) { seenEvents.current.add(e.id); freshEvents.push(e); }
          }
          const reqs = (turn.state?.required_actions ?? []) as Array<{ type?: string }>;
          approvalPending = reqs.some((a) => a.type === "tool.approval_required") ||
            freshEvents.some((e) => e.type === "tool.approval_required");
        }

        const artifacts: EvidenceState["artifacts"] = {};
        if (turn) {
          for (const [key, path] of Object.entries(ARTIFACT_PATHS) as [ArtifactKey, string][]) {
            if (fetchedArtifacts.current[key]) continue;
            const res = await downloadArtifact(fetch, session.id, turn.id, path);
            if (res.status === "ok") { artifacts[key] = res.text; fetchedArtifacts.current[key] = true; }
            else if (res.status === "gone") { fetchedArtifacts.current[key] = true; }
          }
        }

        if (!cancelled) {
          setState((prev) => ({
            session, turn, artifacts,
            activity: [...prev.activity, ...freshEvents],
            phase: derive(turn, approvalPending),
            approvalPending,
            loaded: true,
          }));
        }
      } catch { /* network blip — keep last state, retry next tick */ }
      schedule();
    }

    function activeSession() {
      return import("../sfApi").then((m) => m.activeSchemaForgeSession(fetch));
    }
    function schedule() { timer = setTimeout(tick, pollMs); }

    tick();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [pollMs]);

  return state;
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `npx vitest run src/hooks/useEvidence.test.tsx`
Expected: PASS, both tests.

- [ ] **Step 5: Commit**

```bash
git add ui/src/hooks/useEvidence.ts ui/src/hooks/useEvidence.test.tsx
git commit -m "feat(ui): evidence polling hook (sessions/turns/events/artifacts)"
```

---

## Task 4: Impact graph, safety report, verification panels

**Files:**
- Create: `ui/src/verify.ts`, `ui/src/verify.test.ts`, `ui/src/components/ImpactGraph.tsx`, `ui/src/components/SafetyReport.tsx`, `ui/src/components/VerificationPanel.tsx`
- Test: `ui/src/verify.test.ts`

**Interfaces:**
- Consumes: `useEvidence` state (`artifacts.verify`, `artifacts.graph`, `artifacts.report`).
- Produces: `parseVerify(raw): VerifyJson | null`, `badges(v: VerifyJson | null): Array<{label, ok: boolean | null}>`; components `ImpactGraph({ mmd })`, `SafetyReport({ reportMd, verify })`, `VerificationPanel({ verify })`.

- [ ] **Step 1: Write the failing verify.ts tests**

`ui/src/verify.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { parseVerify, badges } from "./verify";

const good = JSON.stringify({
  alembic_ok: true, pytest_ok: true, parity_ok: true,
  diff: { added_tables: ["user_profiles"], removed_tables: [], added_columns: [], removed_columns: ["users.address", "users.date_of_birth"] },
  explain: [{ query: "find_by_email", ms: 1.4, ms_before: 1.4 }],
});

describe("parseVerify", () => {
  it("parses valid JSON", () => {
    const v = parseVerify(good);
    expect(v?.alembic_ok).toBe(true);
    expect(v?.diff.added_tables).toEqual(["user_profiles"]);
  });
  it("returns null on invalid JSON", () => {
    expect(parseVerify("not json")).toBeNull();
    expect(parseVerify("")).toBeNull();
  });
});

describe("badges", () => {
  it("maps ok fields to badges", () => {
    const b = badges(parseVerify(good));
    expect(b).toEqual([
      { label: "Migration", ok: true },
      { label: "Tests", ok: true },
      { label: "Parity", ok: true },
    ]);
  });
  it("treats null parity as neutral (null ok)", () => {
    const v = parseVerify(JSON.stringify({ alembic_ok: true, pytest_ok: false, parity_ok: null }));
    const b = badges(v);
    expect(b[2]).toEqual({ label: "Parity", ok: null });
  });
  it("returns neutral badges for unparsable input", () => {
    expect(badges(null).every((b) => b.ok === null)).toBe(true);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/verify.test.ts`
Expected: FAIL — `Cannot find module './verify'`.

- [ ] **Step 3: Write verify.ts**

```ts
export interface VerifyJson {
  alembic_ok: boolean;
  pytest_ok: boolean;
  parity_ok: boolean | null;
  alembic_output?: string;
  pytest_output?: string;
  parity_output?: string;
  diff: Record<string, string[]>;
  explain: Array<{ query: string; ms: number; ms_before: number | null }>;
}

export function parseVerify(raw: string | null): VerifyJson | null {
  if (!raw) return null;
  try {
    const j = JSON.parse(raw) as VerifyJson;
    if (typeof j.alembic_ok !== "boolean" || typeof j.pytest_ok !== "boolean") return null;
    return j;
  } catch { return null; }
}

export function badges(v: VerifyJson | null): Array<{ label: string; ok: boolean | null }> {
  if (!v) return [
    { label: "Migration", ok: null },
    { label: "Tests", ok: null },
    { label: "Parity", ok: null },
  ];
  return [
    { label: "Migration", ok: v.alembic_ok },
    { label: "Tests", ok: v.pytest_ok },
    { label: "Parity", ok: v.parity_ok ?? null },
  ];
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run src/verify.test.ts`
Expected: PASS.

- [ ] **Step 5: Write ImpactGraph.tsx**

```tsx
import { useEffect, useId, useState } from "react";
import mermaid from "mermaid";

mermaid.initialize({ startOnLoad: false, theme: "dark" });

export function ImpactGraph({ mmd }: { mmd: string | null }) {
  const uid = useId().replace(/[^a-zA-Z0-9]/g, "");
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!mmd) { setSvg(null); setError(null); return; }
    let live = true;
    mermaid.render(`sfgraph-${uid}`, mmd)
      .then(({ svg: out }) => { if (live) { setSvg(out); setError(null); } })
      .catch((e: Error) => { if (live) { setSvg(null); setError(String(e?.message ?? e)); } });
    return () => { live = false; };
  }, [mmd, uid]);

  if (error) return <div className="p-4 text-sm" style={{ color: "var(--sf-fail)" }}>Could not render graph: {error}</div>;
  if (!svg) return <div className="p-4 text-sm" style={{ color: "var(--sf-muted)" }}>Waiting for graph.mmd…</div>;
  return <div className="p-4 overflow-auto" dangerouslySetInnerHTML={{ __html: svg }} />;
}
```

- [ ] **Step 6: Write SafetyReport.tsx**

```tsx
import ReactMarkdown from "react-markdown";
import { parseVerify, badges } from "../verify";

function Badge({ ok, label }: { ok: boolean | null; label: string }) {
  const color = ok === true ? "var(--sf-ok)" : ok === false ? "var(--sf-fail)" : "var(--sf-muted)";
  return (
    <span className="rounded px-2 py-0.5 text-xs font-semibold border" style={{ color, borderColor: color }}>
      {label}: {ok === null ? "n/a" : ok ? "PASS" : "FAIL"}
    </span>
  );
}

export function SafetyReport({ reportMd, verify }: { reportMd: string | null; verify: string | null }) {
  const v = parseVerify(verify);
  return (
    <div className="space-y-3 p-4">
      {v && <div className="flex flex-wrap gap-2">{badges(v).map((b) => <Badge key={b.label} {...b} />)}</div>}
      {reportMd ? (
        <div className="prose prose-sm max-w-none" style={{ color: "var(--sf-text)" }}>
          <ReactMarkdown>{reportMd}</ReactMarkdown>
        </div>
      ) : (
        <div className="text-sm" style={{ color: "var(--sf-muted)" }}>Waiting for report.md…</div>
      )}
    </div>
  );
}
```

- [ ] **Step 7: Write VerificationPanel.tsx**

```tsx
import { parseVerify } from "../verify";

function Row({ label, ok, output }: { label: string; ok: boolean | null; output?: string }) {
  const color = ok === true ? "var(--sf-ok)" : ok === false ? "var(--sf-fail)" : "var(--sf-muted)";
  return (
    <div className="border rounded p-2" style={{ borderColor: "var(--sf-border)" }}>
      <div className="flex justify-between text-sm">
        <span>{label}</span>
        <span style={{ color }}>{ok === null ? "n/a" : ok ? "PASS" : "FAIL"}</span>
      </div>
      {output && <details className="text-xs mt-1" style={{ color: "var(--sf-muted)" }}><summary>output</summary><pre className="whitespace-pre-wrap">{output}</pre></details>}
    </div>
  );
}

export function VerificationPanel({ verify }: { verify: string | null }) {
  const v = parseVerify(verify);
  if (!v) return <div className="p-4 text-sm" style={{ color: "var(--sf-muted)" }}>Waiting for verify.json…</div>;
  return (
    <div className="space-y-2 p-4">
      <Row label="Alembic migration" ok={v.alembic_ok} output={v.alembic_output} />
      <Row label="Application tests" ok={v.pytest_ok} output={v.pytest_output} />
      <Row label="Data parity" ok={v.parity_ok} output={v.parity_output} />
      <div className="text-sm font-semibold pt-2">Query performance (EXPLAIN ANALYZE, ms)</div>
      <table className="w-full text-xs" style={{ color: "var(--sf-text)" }}>
        <thead><tr className="text-left" style={{ color: "var(--sf-muted)" }}><th>query</th><th>before</th><th>after</th></tr></thead>
        <tbody>
          {(v.explain ?? []).map((e) => (
            <tr key={e.query} className="border-t" style={{ borderColor: "var(--sf-border)" }}>
              <td className="py-1 pr-2">{e.query}</td>
              <td className="py-1 pr-2">{e.ms_before ?? "n/a"}</td>
              <td className="py-1">{e.ms}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="text-xs" style={{ color: "var(--sf-muted)" }}>Schema diff: {JSON.stringify(v.diff)}</div>
    </div>
  );
}
```

- [ ] **Step 8: Commit**

```bash
git add ui/src/verify.ts ui/src/verify.test.ts ui/src/components/ImpactGraph.tsx ui/src/components/SafetyReport.tsx ui/src/components/VerificationPanel.tsx
git commit -m "feat(ui): impact graph, safety report, verification panels"
```

---

## Task 5: Changes + Activity panels, approval glow, wire the panel

**Files:**
- Create: `ui/src/diff.ts`, `ui/src/diff.test.ts`, `ui/src/components/ChangesPanel.tsx`, `ui/src/components/ActivityPanel.tsx`
- Modify: `ui/src/components/EvidencePanel.tsx`

**Interfaces:**
- Consumes: `useEvidence` state; `parseUnifiedDiff`; `ARTIFACT_PATHS`.
- Produces: `parseUnifiedDiff(patch: string): DiffLine[]` where `DiffLine = { kind: "add" | "del" | "ctx" | "hunk" | "meta"; text: string }`; `ChangesPanel({ sql, diff })`; `ActivityPanel({ activity })`; final `EvidencePanel` with tabs + glow.

- [ ] **Step 1: Write the failing diff tests**

`ui/src/diff.test.ts`:
```ts
import { describe, it, expect } from "vitest";
import { parseUnifiedDiff } from "./diff";

const patch = [
  "diff --git a/demo-app/app/models.py b/demo-app/app/models.py",
  "index 111..222 100644",
  "--- a/demo-app/app/models.py",
  "+++ b/demo-app/app/models.py",
  "@@ -10,3 +10,4 @@ class User(Base):",
  "     email: Mapped[str]",
  "-    address: Mapped[str]",
  "+    # address moved to UserProfile",
  "     name: Mapped[str]",
  "",
].join("\n");

describe("parseUnifiedDiff", () => {
  it("skips header lines before the first hunk", () => {
    const lines = parseUnifiedDiff(patch);
    expect(lines.every((l) => l.kind !== "meta" || l.text.startsWith("---") || l.text.startsWith("+++"))).toBe(true);
  });
  it("classifies +/-/context lines", () => {
    const kinds = parseUnifiedDiff(patch).map((l) => l.kind);
    expect(kinds).toContain("add");
    expect(kinds).toContain("del");
    expect(kinds).toContain("ctx");
    expect(kinds).toContain("hunk");
  });
  it("drops diff --git/index noise", () => {
    expect(parseUnifiedDiff(patch).some((l) => l.text.startsWith("diff --git"))).toBe(false);
  });
  it("returns [] for empty input", () => {
    expect(parseUnifiedDiff("")).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/diff.test.ts`
Expected: FAIL — `Cannot find module './diff'`.

- [ ] **Step 3: Write diff.ts**

```ts
export type DiffLine = { kind: "add" | "del" | "ctx" | "hunk" | "meta"; text: string };

export function parseUnifiedDiff(patch: string): DiffLine[] {
  const out: DiffLine[] = [];
  let inHunk = false;
  for (const line of patch.split("\n")) {
    if (line.startsWith("@@")) { inHunk = true; out.push({ kind: "hunk", text: line }); continue; }
    if (line.startsWith("--- ") || line.startsWith("+++ ")) { if (inHunk) out.push({ kind: "meta", text: line }); continue; }
    if (!inHunk) continue;
    if (line.startsWith("+") && !line.startsWith("+++")) out.push({ kind: "add", text: line });
    else if (line.startsWith("-") && !line.startsWith("---")) out.push({ kind: "del", text: line });
    else out.push({ kind: "ctx", text: line });
  }
  return out;
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run src/diff.test.ts`
Expected: PASS.

- [ ] **Step 5: Write ChangesPanel.tsx**

```tsx
import { parseUnifiedDiff } from "../diff";

const LINE_COLORS = { add: "#34d399", del: "#f87171", ctx: "#94a3b8", hunk: "#818cf8", meta: "#64748b" } as const;

export function ChangesPanel({ sql, diff }: { sql: string | null; diff: string | null }) {
  return (
    <div className="space-y-4 p-4 text-xs">
      <section>
        <div className="font-semibold text-sm mb-1">Migration SQL (0001 → 0002)</div>
        {sql ? (
          <pre className="overflow-auto rounded border p-2 whitespace-pre-wrap" style={{ borderColor: "var(--sf-border)", color: "var(--sf-text)" }}>{sql}</pre>
        ) : <div style={{ color: "var(--sf-muted)" }}>Waiting for migration.sql…</div>}
      </section>
      <section>
        <div className="font-semibold text-sm mb-1">Code diff</div>
        {diff ? (
          <div className="rounded border overflow-auto" style={{ borderColor: "var(--sf-border)" }}>
            {parseUnifiedDiff(diff).map((l, i) => (
              <div key={i} className="whitespace-pre-wrap px-2" style={{ color: LINE_COLORS[l.kind] }}>{l.text}</div>
            ))}
          </div>
        ) : <div style={{ color: "var(--sf-muted)" }}>Waiting for diff.patch…</div>}
      </section>
    </div>
  );
}
```

- [ ] **Step 6: Write ActivityPanel.tsx**

```tsx
import type { ApiEvent } from "../sfApi";

const INTERESTING = new Set(["sandbox.created", "tool.request", "tool.response", "thread.created", "thread.done"]);

function threadName(e: ApiEvent): string {
  if (e.thread_id === "main") return "root";
  const info = e.agent_info as { name?: string } | undefined;
  return info?.name ?? e.thread_id ?? "?";
}

function oneLine(e: ApiEvent): string {
  const c = e.content as string | undefined;
  if (typeof c === "string" && c.length > 0) return c.length > 90 ? c.slice(0, 90) + "…" : c;
  return e.type;
}

export function ActivityPanel({ activity }: { activity: ApiEvent[] }) {
  const rows = activity.filter((e) => INTERESTING.has(e.type));
  if (rows.length === 0) return <div className="p-4 text-sm" style={{ color: "var(--sf-muted)" }}>No activity yet…</div>;
  return (
    <div className="p-4 text-xs space-y-1.5">
      {rows.map((e) => (
        <div key={e.id} className="flex gap-2">
          <span className="shrink-0 rounded px-1 py-0.5 border" style={{ color: "var(--sf-accent)", borderColor: "var(--sf-border)" }}>{threadName(e)}</span>
          <span style={{ color: "var(--sf-text)" }}>{oneLine(e)}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 7: Rewrite EvidencePanel.tsx with tabs + approval glow**

```tsx
import { useMemo, useState } from "react";
import { useEvidence } from "../hooks/useEvidence";
import { ImpactGraph } from "./ImpactGraph";
import { SafetyReport } from "./SafetyReport";
import { ChangesPanel } from "./ChangesPanel";
import { VerificationPanel } from "./VerificationPanel";
import { ActivityPanel } from "./ActivityPanel";

const TABS = ["Impact", "Report", "Changes", "Verification", "Activity"] as const;
type Tab = (typeof TABS)[number];

export function EvidencePanel() {
  const ev = useEvidence();
  const [tab, setTab] = useState<Tab>("Impact");
  const [visited, setVisited] = useState<Set<Tab>>(new Set(["Impact"]));
  const unReviewed = useMemo(
    () => ev.approvalPending ? TABS.filter((t) => !visited.has(t)) : [],
    [ev.approvalPending, visited],
  );

  const select = (t: Tab) => { setVisited((v) => new Set(v).add(t)); setTab(t); };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-3 py-2 text-xs" style={{ borderColor: "var(--sf-border)", color: "var(--sf-muted)" }}>
        <span className="font-semibold">EVIDENCE</span>
        {ev.approvalPending && <span className="animate-pulse font-semibold" style={{ color: "#fbbf24" }}>⚠ review before approving</span>}
        {!ev.approvalPending && <span>{ev.phase === "running" ? "agent working…" : ev.phase}</span>}
      </div>
      <div className="flex gap-1 border-b px-2 py-1" style={{ borderColor: "var(--sf-border)" }}>
        {TABS.map((t) => (
          <button key={t} onClick={() => select(t)} className={`rounded px-2 py-1 text-xs ${tab === t ? "" : "opacity-70"}`}
            style={{
              background: tab === t ? "var(--sf-panel)" : "transparent",
              color: "var(--sf-text)",
              boxShadow: unReviewed.includes(t) ? "0 0 0 1px #fbbf24" : undefined,
            }}>
            {t}{unReviewed.includes(t) ? " ●" : ""}
          </button>
        ))}
      </div>
      <div className="flex-1 min-h-0 overflow-auto">
        {tab === "Impact" && <ImpactGraph mmd={ev.artifacts.graph ?? null} />}
        {tab === "Report" && <SafetyReport reportMd={ev.artifacts.report ?? null} verify={ev.artifacts.verify ?? null} />}
        {tab === "Changes" && <ChangesPanel sql={ev.artifacts.sql ?? null} diff={ev.artifacts.diff ?? null} />}
        {tab === "Verification" && <VerificationPanel verify={ev.artifacts.verify ?? null} />}
        {tab === "Activity" && <ActivityPanel activity={ev.activity} />}
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Run the full UI test suite**

Run: `cd ui && npx vitest run`
Expected: PASS — all sfApi, useEvidence, verify, diff tests.

- [ ] **Step 9: Commit**

```bash
git add ui/src/diff.ts ui/src/diff.test.ts ui/src/components/ChangesPanel.tsx ui/src/components/ActivityPanel.tsx ui/src/components/EvidencePanel.tsx
git commit -m "feat(ui): changes + activity panels, approval-glow evidence tabs"
```

---

## Task 6: Local end-to-end verification + PR #18

**Files:** none (verification).

**Interfaces:** uses everything from Tasks 1-5.

- [ ] **Step 1: Confirm local services are up (do NOT touch them)**

Run:
```bash
ss -ltnp 2>/dev/null | grep -E ':8790|:8001|:8002|:5433' | awk '{print $4, $6}'
```
Expected: listeners on `[::1]:8790`, `0.0.0.0:8001`, `0.0.0.0:8002`, `127.0.0.1:5433`. If any are down, ask the user to start them (`scripts/run_mcp_servers.sh`, their trueforge process) — never start them yourself.

- [ ] **Step 2: Create a scratch session + turn via the API (read-only probe)**

Run with the repo venv python:
```bash
cd /home/utsav/Github/schemaforge && .vevn/bin/python - <<'EOF'
import httpx
r = httpx.get("http://[::1]:8790/api/v1/sessions", timeout=10)
print(r.status_code, len(r.json().get("data", [])))
EOF
```
Expected: `200` and a number. This confirms the proxy target answers before the browser test.

- [ ] **Step 3: Drive the UI in a browser against the local harness**

With `npm run dev` running, drive a browser to `http://localhost:5173`:
- Confirm the chat renders and the `schemaforge` agent is selectable.
- Send the locked trigger prompt: `Split the users table into users and user_profiles. user_profiles gets id, user_id (1:1 FK), address, date_of_birth. users keeps id, name, email. The API response shape of /users must not change.`
- Acceptance (watch until the run pauses at the approval gate or ends):
  - `Impact` tab eventually renders a mermaid graph (26 nodes / 43 edges for the users split).
  - `Report` tab shows PASS/PASS/PASS badges + the markdown report body.
  - `Changes` tab shows migration SQL and a colored diff.
  - `Verification` tab shows the three rows + the EXPLAIN table.
  - `Activity` tab shows sandbox/tool events grouped by thread.
  - When the turn pauses for approval, the header shows the ⚠ glow and the tab dots appear (Task 12 live run takes ~10-20 min; if the turn hits a 429 rate-limit error, retry the prompt in a new session).
- Do NOT approve/apply — the panel evidence is what is being verified.

- [ ] **Step 4: Commit any fixes from Step 3**

```bash
git add ui/
git commit -m "fix(ui): adjustments from local end-to-end run"
```

- [ ] **Step 5: Open PR #18 and trigger Qodo**

```bash
cd /home/utsav/Github/schemaforge && git push -u origin feat/evidence-ui
gh pr create --title "feat: evidence-first UI for the SchemaForge agent" --body "Evidence panel (graph/report/changes/verification/activity) beside the TrueForge SDK chat. No blind approvals." --base main
gh pr comment <PR_URL> --body "/agentic_review"
```
Wait for Qodo review; fix findings in follow-up commits on the branch; re-trigger `/agentic_review` until clean (allow multiple rounds — see PR #14 history). Merge via squash only when Qodo is clean, then delete the branch.

- [ ] **Step 6: Post-merge sanity**

Run: `git checkout main && git pull && git log --oneline -1`
Expected: the squash commit of PR #18 at HEAD; working tree clean.

---

## Task 7: Artifact contract — verify.json + SKILL.md artifact lines (PR #19)

**Files:**
- Modify: `core/schemaforge_core/report.py` (add `render_json`), `core/schemaforge_core/pipeline.py:160-167` (write verify.json), `core/tests/test_report.py` (new test), `skills/schemaforge-migration/SKILL.md` (two artifact lines + delete duplicated steps block)
- Test: `core/tests/test_report.py`

**Interfaces:**
- Consumes: existing `render_report(r)` dict shape (`alembic_ok`, `pytest_ok`, `parity_ok`, `diff`, `explain`).
- Produces: `render_json(r: dict) -> dict`; `verify.json` written next to `report.md` at `out.parent / "verify.json"`; SKILL.md now guarantees `out/migration.sql` and `out/diff.patch`.

- [ ] **Step 1: Write the failing test**

Append to `core/tests/test_report.py`:
```python
def test_render_json_shape():
    from schemaforge_core.report import render_json

    r = {
        "alembic_ok": True,
        "pytest_ok": True,
        "parity_ok": True,
        "diff": {"added_tables": ["user_profiles"], "removed_tables": [],
                 "added_columns": [], "removed_columns": ["users.address", "users.date_of_birth"]},
        "explain": [{"query": "find_by_email", "ms": 1.4, "ms_before": None}],
    }
    j = render_json(r)
    assert j["alembic_ok"] is True
    assert j["parity_ok"] is True
    assert j["diff"]["added_tables"] == ["user_profiles"]
    assert j["explain"][0]["query"] == "find_by_email"
    # machine-readable only — no markdown text
    assert "#" not in str(j)
```

- [ ] **Step 2: Run to verify failure**

Run:
```bash
cd /home/utsav/Github/schemaforge && .vevn/bin/python -m pytest core/tests/test_report.py -q
```
Expected: FAIL — `ImportError: cannot import name 'render_json'`.

- [ ] **Step 3: Add render_json to report.py**

Append to `core/schemaforge_core/report.py`:
```python
def render_json(r: dict) -> dict:
    """Machine-readable subset of the safety report (consumed by the UI)."""
    return {
        "alembic_ok": bool(r.get("alembic_ok")),
        "pytest_ok": bool(r.get("pytest_ok")),
        "parity_ok": r.get("parity_ok"),  # None when no parity SQL was given
        "diff": r.get("diff", {}),
        "explain": r.get("explain", []),
    }
```

- [ ] **Step 4: Wire verify.json into cmd_verify**

In `core/schemaforge_core/pipeline.py`, replace:
```python
    report = render_report(result)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    print(report)
```
with:
```python
    report = render_report(result)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report)
    (out.parent / "verify.json").write_text(
        json.dumps(render_json(result), indent=2) + "\n"
    )
    print(report)
```
(import line 28 `from .report import render_report` becomes `from .report import render_json, render_report`)

- [ ] **Step 5: Run the core test suite**

Run:
```bash
cd /home/utsav/Github/schemaforge && .vevn/bin/python -m pytest core/tests/ -q
```
Expected: PASS, all tests (existing + new).

- [ ] **Step 6: Edit SKILL.md — artifact lines + dedupe**

In `skills/schemaforge-migration/SKILL.md`:
1. In step 6 (after authoring the migration), append:
   `Then `git diff > /workspace/out/diff.patch` (code changes only — the diff the UI shows).`
2. In step 9 (approval, offline SQL), change:
   `cd demo-app && alembic upgrade 0001:head --sql` → `cd demo-app && alembic upgrade 0001:head --sql | tee /workspace/out/migration.sql`
3. Delete the duplicated block (current lines 65-75: the second `8. Measure DDL wall time…`, `9. Present out/report.md…`, `10. On approval…`, `11. PR…`) — it is superseded by steps 6-10 and must not exist twice.

- [ ] **Step 7: Re-register skill + agent (live harness)**

Run:
```bash
cd /home/utsav/Github/schemaforge && set -a && . ./.env && set +a && \
  .vevn/bin/python scripts/import_skill.py && \
  .vevn/bin/python scripts/apply_agent.py
```
Expected: both scripts exit 0; then verify:
```bash
.vevn/bin/python - <<'EOF'
import httpx, os
r = httpx.get(f"{os.environ['TRUEFORGE_URL']}/api/v1/agents", timeout=10)
a = next(x for x in r.json()["data"] if x["name"] == "schemaforge")
m = a["manifest"]
print(m["model"]["name"])                       # cloudflare/deepseek-v4-flash
print(m["skills"])                              # [{'name': 'schemaforge-migration'}]
print("orphan-guard" in m["instructions"], "migration.sql" in m["instructions"])
EOF
```
Expected: `cloudflare/deepseek-v4-flash`, the skill list, `True True`.

- [ ] **Step 8: Open PR #19 + Qodo**

```bash
cd /home/utsav/Github/schemaforge && git checkout -b feat/artifact-contract && git push -u origin feat/artifact-contract
gh pr create --title "feat: artifact contract — verify.json + out/migration.sql + out/diff.patch" --base main --body "Machine-readable verify output for the evidence UI; SKILL.md now emits migration.sql/diff.patch at stable paths; dedupes stale steps 8-11."
gh pr comment <PR_URL> --body "/agentic_review"
```
Wait for Qodo clean; squash-merge; delete branch; `git checkout main && git pull`.

- [ ] **Step 9: Verify the artifact contract end-to-end in a sandbox**

Start one live turn (browser against local UI or API) with the locked split prompt; after the run passes verify (before approval), confirm via the deployed-UI-equivalent calls that all five artifact paths return 200:
```bash
# substitute real session/turn ids from the run
for p in graph.mmd report.md verify.json migration.sql diff.patch; do
  curl -s -o /dev/null -w "$p %{http_code}\n" "http://[::1]:8790/api/v1/sessions/<SID>/turns/<TID>/download-sandbox-file?path=/workspace/out/$p"
done
```
Expected: all five print `200` (or `404` for files the agent legitimately has not written yet — `migration.sql`/`diff.patch` appear only after authoring/approval phases; the panels' polling already handles this).

---

## Task 8: Neon — two Postgres databases + seed

**Files:** none (infrastructure; record connection strings in the deploy task).

**Interfaces:**
- Produces: `NEON_TRUEFORGE_URL` (harness metadata DB) and `NEON_BOOKSTORE_URL` (prod migration target) — both `postgresql://...?...sslmode=require`.

- [ ] **Step 1: Create the Neon project**

Use the Neon dashboard or CLI:
```bash
neon projects create --name schemaforge 2>/dev/null || echo "create via dashboard: console.neon.tech"
```
Expected: a project with a connection string for the default `neondb` database.

- [ ] **Step 2: Create the two databases**

Using the project's connection string (psql):
```bash
psql "$NEON_BASE_URL/postgres" -c "CREATE DATABASE trueforge;"
psql "$NEON_BASE_URL/postgres" -c "CREATE DATABASE bookstore;"
```
Expected: `CREATE DATABASE` ×2. Record `.../trueforge?sslmode=require` and `.../bookstore?sslmode=require`.

- [ ] **Step 3: Seed bookstore pre-split (200k users / 5k books)**

Run:
```bash
cd /home/utsav/Github/schemaforge && DATABASE_URL="$NEON_BOOKSTORE_URL" bash scripts/seed_prod.sh
```
Expected: `seeded: users=200000, books=5000` and `row counts: users=200000`.

- [ ] **Step 4: Verify the baseline**

Run:
```bash
psql "$NEON_BOOKSTORE_URL" -tAc "SELECT version_num FROM alembic_version; SELECT count(*) FROM users; SELECT count(*) FROM books;"
```
Expected: `0001`, `200000`, `5000`.

---

## Task 9: Cloudflare deploy — Containers + Pages Function + Pages site (PR #20)

**Files:**
- Create: `deploy/wrangler.toml`, `deploy/functions/api/[[path]].js`, `deploy/Dockerfile.trueforge`, `deploy/Dockerfile.postgres-mcp`, `deploy/Dockerfile.github-mcp`
- Modify: `ui/src/App.tsx` (baseUrl stays `/` — no change needed; verify), `.gitignore` (add `deploy/.wrangler`)

**Interfaces:**
- Consumes: `NEON_TRUEFORGE_URL`, `NEON_BOOKSTORE_URL` (Task 8), repo MCP server sources (`mcp-servers/postgres-mcp/server.py`, `mcp-servers/github-mcp/server.py`).
- Produces: a deployed `https://<project>.pages.dev` where `/api/*` reaches hosted-mode TrueForge and the UI is served statically.

**Deployment model (verified against CF docs 2026-08-13):** CF Containers run arbitrary Docker images with **ephemeral disk** (Postgres must stay external → Neon). Containers are controlled from a Worker/Pages Function via Durable-Object container bindings; `sleepAfter` defaults to 10 min, override `onActivityExpired()` to keep the demo stack warm. Requests pass through the Function, so the deployed UI and `/api` are **same-origin** — no CORS config anywhere. Docker Hub images (redis) and local Dockerfiles are both supported.

- [ ] **Step 1: Write deploy/wrangler.toml**

```toml
name = "schemaforge-backend"
compatibility_date = "2026-08-28"
compatibility_flags = ["nodejs_compat"]
pages_build_output_dir = "../ui/dist"

[[containers]]
class_name = "TrueForgeServer"
image = "./Dockerfile.trueforge"
max_instances = 1

[[containers]]
class_name = "PostgresMcp"
image = "./Dockerfile.postgres-mcp"
max_instances = 1

[[containers]]
class_name = "GithubMcp"
image = "./Dockerfile.github-mcp"
max_instances = 1

[[containers]]
class_name = "Redis"
image = "redis:7-alpine"
max_instances = 1

[[durable_objects.bindings]]
class_name = "TrueForgeServer"
name = "TRUEFORGE_SERVER"

[[durable_objects.bindings]]
class_name = "PostgresMcp"
name = "POSTGRES_MCP"

[[durable_objects.bindings]]
class_name = "GithubMcp"
name = "GITHUB_MCP"

[[durable_objects.bindings]]
class_name = "Redis"
name = "REDIS"

[[migrations]]
new_sqlite_classes = ["TrueForgeServer", "PostgresMcp", "GithubMcp", "Redis"]
tag = "v1"

[vars]
# non-secret runtime config; secrets go via `wrangler secret put`
NEON_TRUEFORGE_URL = "postgresql://USER:PASS@HOST/trueforge?sslmode=require"
NEON_BOOKSTORE_URL = "postgresql://USER:PASS@HOST/bookstore?sslmode=require"
```

- [ ] **Step 2: Write the Pages Function router**

`deploy/functions/api/[[path]].js`:
```js
import { getContainer } from "@cloudflare/containers";

export async function onRequest(context) {
  const { env, request } = context;
  const url = new URL(request.url);
  if (!url.pathname.startsWith("/api/")) {
    return new Response("Not found", { status: 404 });
  }
  const tf = getContainer(env.TRUEFORGE_SERVER, "main");
  return tf.fetch(request);
}
```
The container classes keep the stack alive by overriding `onActivityExpired` — add that to a shared helper and reference it from each class (verify the exact override API against `node_modules/@cloudflare/containers` types in Step 4).

- [ ] **Step 3: Write the three Dockerfiles**

`deploy/Dockerfile.trueforge`:
```dockerfile
FROM node:22-bookworm-slim
RUN npm install -g @truefoundry/trueforge@0.1.4
ENV STANDALONE=false PORT=8791
EXPOSE 8791
CMD ["npx", "@truefoundry/trueforge"]
```

`deploy/Dockerfile.postgres-mcp`:
```dockerfile
FROM python:3.12-slim
WORKDIR /srv
COPY mcp-servers/postgres-mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mcp-servers/postgres-mcp/server.py .
ENV DATABASE_URL=postgresql://USER:PASS@HOST/bookstore?sslmode=require
EXPOSE 8001
CMD ["python", "server.py"]
```

`deploy/Dockerfile.github-mcp`:
```dockerfile
FROM python:3.12-slim
WORKDIR /srv
COPY mcp-servers/github-mcp/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY mcp-servers/github-mcp/server.py .
EXPOSE 8002
CMD ["python", "server.py"]
```
Note: build context must be the repo root so the `COPY mcp-servers/...` paths resolve — set it in `wrangler.toml` if supported, else copy the two server dirs into `deploy/` before building.

- [ ] **Step 4: Install @cloudflare/containers + verify container/env wiring**

Run:
```bash
cd deploy && npm init -y && npm install -D @cloudflare/containers
```
Then read the local types to confirm: (a) the `Container` class API (`sleepAfter`, `onActivityExpired`, `defaultPort`), (b) how env vars reach a container (platform env from `[vars]`/secrets vs image `ENV`), (c) the exact internal-hostname mechanism containers use to reach each other (the trueforge container must reach postgres-mcp/github-mcp at their internal URLs — if hostnames are not available, expose the two MCP servers through additional Function routes with a shared `X-SF-TOKEN` header and put that URL in the agent manifest).
Record the verified facts as comments at the top of `wrangler.toml`.

- [ ] **Step 5: Deploy the backend + frontend**

Run:
```bash
cd ui && npm run build          # produces ui/dist
cd ../deploy
wrangler secret put DAYTONA_API_KEY      # paste from .env
wrangler secret put GITHUB_PERSONAL_ACCESS_TOKEN
wrangler secret put CLOUDFLARE_AUTH_TOKEN
wrangler secret put CLOUDFLARE_ACCOUNT_ID
wrangler deploy
```
Expected: `wrangler deploy` uploads the Pages site (built from `ui/dist`), creates the four container classes, and prints a `https://<project>.pages.dev` URL.

- [ ] **Step 6: Configure the deployed TrueForge (model provider, skill, agent)**

Run (against the deployed instance — this is a one-time registration; the container disk is ephemeral so this must be re-runnable after restarts, document it in README):
```bash
cd /home/utsav/Github/schemaforge && set -a && . ./.env && set +a
export TRUEFORGE_URL="https://<project>.pages.dev"
.vevn/bin/python scripts/register_model_provider.py   # or inline: PUT /api/v1/settings/model-providers with the cloudflare provider manifest
.vevn/bin/python scripts/import_skill.py
.vevn/bin/python scripts/apply_agent.py
```
Expected: all exit 0; then `GET /api/v1/agents` on the deployed URL shows `schemaforge` with model `cloudflare/deepseek-v4-flash`.

- [ ] **Step 7: Verify the deployed stack responds**

Run:
```bash
curl -s https://<project>.pages.dev/api/v1/sessions | head -c 200
curl -s -o /dev/null -w "%{http_code}\n" https://<project>.pages.dev/
```
Expected: JSON from the sessions endpoint (the container answers), and `200` for the UI.

---

## Task 10: Deployed judge-flow smoke + README + PR #20

**Files:**
- Modify: `README.md` (Deployed section)

- [ ] **Step 1: Full judge-flow on the deployed URL**

Drive a browser to `https://<project>.pages.dev`: send the locked split prompt, wait for the run (10-20 min; retry on 429), then:
- Acceptance (same as Task 6 Step 3, now against the deployed URL): all five panels populate; the turn pauses on the approval gate with the ⚠ glow; **do not approve** — the deploy is proven at the pause.
- Also verify a reconnect: reload the page mid-turn — the SDK's session history must resume the same session (session persistence + our `activeSchemaForgeSession` heuristic both work across reloads).

- [ ] **Step 2: Write the README Deployed section**

Append to `README.md`:
```markdown
## Deployed

Live at **https://<project>.pages.dev** — the full stack runs on Cloudflare:
Pages (this UI), Containers (TrueForge + MCP servers + Redis), Neon Postgres
(metadata + prod `bookstore`), Workers AI (model), Daytona (sandbox).

Everything is same-origin: the Pages Function routes `/api/*` to the
TrueForge container; no CORS configuration. The database is external by
design — CF Container disk is ephemeral.

Re-registration after a container restart (the harness metadata DB is on
Neon, but the agent/skill/model-provider registrations are applied via the
API): see `deploy/README.md` / the steps in `docs/superpowers/plans/2026-08-28-ui-and-deployment.md` Task 9 Step 6.
```

- [ ] **Step 3: Commit deploy work + open PR #20**

```bash
cd /home/utsav/Github/schemaforge && git checkout -b feat/cf-deploy && git add deploy/ ui/ README.md && git commit -m "feat: Cloudflare deploy — Pages UI, containers, Neon wiring, README Deployed section"
git push -u origin feat/cf-deploy
gh pr create --title "feat: Cloudflare deployment (Pages + Containers + Neon)" --base main --body "Full-stack deploy: same-origin /api via Pages Function, TrueForge + MCP + Redis containers, Neon Postgres, README Deployed section."
gh pr comment <PR_URL> --body "/agentic_review"
```
Wait for Qodo clean; squash-merge; delete branch.

- [ ] **Step 4: Final acceptance — the submission's deployed link**

Run: `curl -s -o /dev/null -w "%{http_code}\n" https://<project>.pages.dev/`
Expected: `200`. Paste `https://<project>.pages.dev` into the submission's "Deployed link to project" field.

---

## Self-Review (completed by the plan author)

**1. Spec coverage:**
- Evidence-first product UI → Tasks 1-6. All five panels → Task 4 (impact/report/verification) + Task 5 (changes/activity). Approval rule → Task 5 Step 7 (⚠ glow + tab dots).
- Option B (SDK + panels) → Task 1 (SDK chat shell) + panels. Artifact contract → Task 7 (verify.json, migration.sql, diff.patch) + Task 6/9 verification of paths.
- Cloudflare stack (Pages + Function router + 4 containers + Neon ×2 + Workers AI + Daytona) → Tasks 8-9. Same-origin CORS solution → Task 9 (Pages Function, no CORS config).
- Fallback ladder → Task 9 Step 4 (MCP hostname contingency + header auth) and the polling-based panels (no SSE dependency anywhere in the UI — SSE is only used by the SDK internally, which is why the plan never wires it).
- Build order demo-safe → Tasks 1-6 filmable locally; deploy (8-10) is additive. README Deployed → Task 10.
**2. Placeholder scan:** no TBD/TODO; every code step is complete. The two URLs with `<project>` are filled from the actual deploy output by the executing engineer (unavoidable — the project name is chosen at deploy time).
**3. Type consistency:** `ArtifactKey`/`ARTIFACT_PATHS` defined in Task 3 and consumed in Tasks 4-5; `VerifyJson`/`parseVerify`/`badges` defined in Task 4, consumed by SafetyReport + VerificationPanel (Task 4) — consistent. `DiffLine`/`parseUnifiedDiff` defined in Task 5. `render_json` defined in Task 7, wired in the same task. `EvidenceState` (Task 3) is the single source for all panels.
**4. Known deviation from spec, flagged:** the spec's "Worker proxy" is implemented as a **Pages Function** (same-origin, no cross-project routing, no CORS) — strictly fewer moving parts, same guarantee. The spec's "SSE through Worker→Container risk" is retired: the panels poll (proven in Task 12), and the SDK owns streaming internally.