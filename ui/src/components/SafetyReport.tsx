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
