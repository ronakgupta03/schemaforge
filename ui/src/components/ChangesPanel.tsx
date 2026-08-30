import { parseUnifiedDiff } from "../diff";

const GUTTER: Record<string, string> = { add: "+", del: "−", hunk: "@" };
const TEXT: Record<string, string> = {
  add: "#34d399",
  del: "#f87171",
  ctx: "var(--sf-text)",
  hunk: "#818cf8",
  meta: "#64748b",
};
const BG: Record<string, string> = {
  add: "rgba(52,211,153,0.10)",
  del: "rgba(248,113,113,0.10)",
  hunk: "rgba(129,140,248,0.08)",
  ctx: "transparent",
  meta: "transparent",
};

export function ChangesPanel({ sql, diff }: { sql: string | null; diff: string | null }) {
  return (
    <div className="space-y-4 text-xs">
      <section>
        <div className="font-semibold text-sm mb-1">Migration SQL</div>
        {sql ? (
          <pre className="overflow-auto rounded border p-3 whitespace-pre-wrap" style={{ borderColor: "var(--sf-border)", color: "var(--sf-text)", background: "var(--sf-panel)" }}>{sql}</pre>
        ) : <div style={{ color: "var(--sf-muted)" }}>Waiting for migration.sql…</div>}
      </section>
      <section>
        <div className="font-semibold text-sm mb-1">Code diff</div>
        {diff ? (
          <div className="rounded border overflow-auto font-mono" style={{ borderColor: "var(--sf-border)", background: "var(--sf-panel)" }}>
            {parseUnifiedDiff(diff).map((l, i) => (
              <div key={i} className="flex whitespace-pre-wrap leading-relaxed" style={{ backgroundColor: BG[l.kind] }}>
                <span className="shrink-0 select-none w-6 text-center" style={{ color: "var(--sf-muted)" }}>
                  {GUTTER[l.kind] ?? ""}
                </span>
                <span className="px-1" style={{ color: TEXT[l.kind] ?? "var(--sf-text)" }}>
                  {l.text}
                </span>
              </div>
            ))}
          </div>
        ) : <div style={{ color: "var(--sf-muted)" }}>Waiting for diff.patch…</div>}
      </section>
    </div>
  );
}
