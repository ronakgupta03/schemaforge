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
