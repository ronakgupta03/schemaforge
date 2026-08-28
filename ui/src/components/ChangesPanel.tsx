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
