import { useEffect, useMemo, useRef, useState } from "react";
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

  const prevApprovalPending = useRef(ev.approvalPending);
  const prevSessionId = useRef(ev.session?.id);
  const prevTurnId = useRef(ev.turn?.id);

  useEffect(() => {
    const approvalJustStarted = !prevApprovalPending.current && ev.approvalPending;
    const scopeChanged = ev.session?.id !== prevSessionId.current || ev.turn?.id !== prevTurnId.current;

    if (approvalJustStarted || scopeChanged) {
      setVisited(new Set(["Impact"]));
    }

    prevApprovalPending.current = ev.approvalPending;
    prevSessionId.current = ev.session?.id;
    prevTurnId.current = ev.turn?.id;
  }, [ev.approvalPending, ev.session?.id, ev.turn?.id]);
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
