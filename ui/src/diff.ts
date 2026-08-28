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
