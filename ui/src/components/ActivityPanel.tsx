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

function statusOf(e: ApiEvent): "ok" | "fail" | "info" {
  const c = (e.content as string) ?? "";
  if (/error|not found|failed|rejected|exception/i.test(c)) return "fail";
  if (e.type === "tool.response") return "ok";
  return "info";
}

export function ActivityPanel({ activity }: { activity: ApiEvent[] }) {
  const rows = activity.filter((e) => INTERESTING.has(e.type));
  if (rows.length === 0) return <div className="text-sm" style={{ color: "var(--sf-muted)" }}>No activity yet…</div>;
  return (
    <div className="text-xs space-y-1.5">
      {rows.map((e) => {
        const status = statusOf(e);
        return (
          <div key={e.id} className="flex gap-2 items-start">
            <span className="shrink-0 select-none text-center w-4 pt-0.5" style={{ color: status === "ok" ? "#34d399" : status === "fail" ? "#f87171" : "var(--sf-muted)" }}>
              {status === "ok" ? "✓" : status === "fail" ? "✕" : "•"}
            </span>
            <span className="shrink-0 rounded px-1 py-0.5 border" style={{ color: "var(--sf-accent)", borderColor: "var(--sf-border)" }}>{threadName(e)}</span>
            <span style={{ color: "var(--sf-text)" }}>{oneLine(e)}</span>
          </div>
        );
      })}
    </div>
  );
}
