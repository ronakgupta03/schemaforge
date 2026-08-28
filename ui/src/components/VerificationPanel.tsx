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
