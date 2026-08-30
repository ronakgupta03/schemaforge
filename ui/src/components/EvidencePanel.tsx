import { useEffect, useMemo, useRef, useState } from "react";
import { useEvidence } from "../hooks/useEvidence";
import { ImpactGraph } from "./ImpactGraph";
import { SafetyReport } from "./SafetyReport";
import { ChangesPanel } from "./ChangesPanel";
import { VerificationPanel } from "./VerificationPanel";
import { ActivityPanel } from "./ActivityPanel";
import { SettingsPanel } from "./SettingsPanel";

const TABS = ["Impact", "Report", "Changes", "Verification", "Activity", "Settings"] as const;
type Tab = (typeof TABS)[number];
const EVIDENCE_TABS: Tab[] = TABS.filter((t) => t !== "Settings");

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
    () => ev.approvalPending ? EVIDENCE_TABS.filter((t) => !visited.has(t as Tab)) : [],
    [ev.approvalPending, visited],
  );

  const select = (t: Tab) => { setVisited((v) => new Set(v).add(t)); setTab(t); };

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b px-3 py-2 text-xs" style={{ borderColor: "var(--sf-border)", color: "var(--sf-muted)" }}>
        <span className="font-semibold tracking-wide">EVIDENCE</span>
        {ev.approvalPending && <span className="animate-pulse font-semibold" style={{ color: "#fbbf24" }}>⚠ review before approving</span>}
        {!ev.approvalPending && <span className="capitalize">{ev.phase === "running" ? "agent working…" : ev.phase}</span>}
      </div>
      <div className="flex border-b" style={{ borderColor: "var(--sf-border)" }}>
        {TABS.map((t) => {
          const active = tab === t;
          const unread = unReviewed.includes(t);
          return (
            <button
              key={t}
              onClick={() => select(t)}
              className={`relative px-3 py-2 text-xs font-medium transition-colors ${active ? "opacity-100" : "opacity-70 hover:opacity-100"}`}
              style={{ color: unread ? "#fbbf24" : "var(--sf-text)" }}
            >
              {t}{unread ? " ●" : ""}
              {active && (
                <span className="absolute bottom-0 left-1 right-1 h-0.5 rounded-t" style={{ background: "var(--sf-accent)" }} />
              )}
            </button>
          );
        })}
      </div>
      <div className="flex-1 min-h-0 overflow-auto p-3">
        {tab === "Impact" && <ImpactGraph mmd={ev.artifacts.graph ?? null} />}
        {tab === "Report" && <SafetyReport reportMd={ev.artifacts.report ?? null} verify={ev.artifacts.verify ?? null} />}
        {tab === "Changes" && <ChangesPanel sql={ev.artifacts.sql ?? null} diff={ev.artifacts.diff ?? null} />}
        {tab === "Verification" && <VerificationPanel verify={ev.artifacts.verify ?? null} />}
        {tab === "Activity" && <ActivityPanel activity={ev.activity} />}
        {tab === "Settings" && <SettingsPanel fetchFn={fetch} />}
      </div>
    </div>
  );
}
