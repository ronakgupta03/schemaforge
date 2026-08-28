export interface AgentRef { type: string; id: string; name: string }
export interface Session {
  id: string; agent: AgentRef; title: string; created_at: string; updated_at: string;
}
export interface Turn {
  id: string; session_id: string; previous_turn_id: string | null;
  input: unknown; state: { status: string; reason?: string; required_actions?: unknown[] };
  created_at: string;
}
export interface ApiEvent { type: string; id: string; turn_id: string; thread_id: string | null; created_at?: string; [k: string]: unknown }
export type ArtifactResult =
  | { status: "ok"; text: string }
  | { status: "pending" }
  | { status: "gone" };

type FetchFn = typeof fetch;

async function getJson<T>(fetchFn: FetchFn, path: string): Promise<T> {
  const res = await fetchFn(path);
  if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
  return (await res.json()) as T;
}

export async function listSessions(fetchFn: FetchFn): Promise<Session[]> {
  const body = await getJson<{ data: Session[] }>(fetchFn, "/api/v1/sessions");
  return body.data ?? [];
}

export async function activeSchemaForgeSession(fetchFn: FetchFn): Promise<Session | null> {
  const sessions = await listSessions(fetchFn);
  const mine = sessions
    .filter((s) => s.agent?.name === "schemaforge")
    .sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  return mine[0] ?? null;
}

export async function listTurns(fetchFn: FetchFn, sessionId: string): Promise<Turn[]> {
  const body = await getJson<{ data: Turn[] }>(fetchFn, `/api/v1/sessions/${sessionId}/turns`);
  return body.data ?? [];
}

export async function listEvents(fetchFn: FetchFn, sessionId: string, turnId: string): Promise<ApiEvent[]> {
  return getJson<ApiEvent[]>(fetchFn, `/api/v1/sessions/${sessionId}/turns/${turnId}/events`);
}

export async function downloadArtifact(fetchFn: FetchFn, sessionId: string, turnId: string, path: string): Promise<ArtifactResult> {
  const url = `/api/v1/sessions/${sessionId}/turns/${turnId}/download-sandbox-file?path=${encodeURIComponent(path)}`;
  const res = await fetchFn(url);
  if (res.status === 200) return { status: "ok", text: await res.text() };
  if (res.status === 404) return { status: "pending" };
  if (res.status === 410 || res.status === 412 || res.status === 413) return { status: "gone" };
  throw new Error(`download ${path} -> ${res.status}`);
}
