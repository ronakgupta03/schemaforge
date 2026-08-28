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
            session, turn,
            artifacts: { ...prev.artifacts, ...artifacts },
            activity: [...prev.activity, ...freshEvents],
            phase: derive(turn, approvalPending),
            approvalPending,
            loaded: true,
          }));
        }
      } catch { /* network blip — keep last state, retry next tick */ }
      schedule();
    }

    async function activeSession() {
      const sessions = await listSessions(fetch);
      const mine = sessions
        .filter((s) => s.agent?.name === "schemaforge")
        .sort((a, b) => (b.updated_at ?? "").localeCompare(a.updated_at ?? ""));
      return mine[0] ?? null;
    }
    function schedule() { timer = setTimeout(tick, pollMs); }

    tick();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [pollMs]);

  return state;
}
