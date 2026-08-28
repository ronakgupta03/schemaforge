import type { FetchFn } from "./sfApi";

const json = async <T>(resOrPromise: Response | Promise<Response>): Promise<T> => {
  const res = await resOrPromise;
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return (await res.json()) as T;
};

export const listModelProviders = (f: FetchFn) =>
  json<{ data: unknown[] }>(f("/api/v1/settings/model-providers")).then((b) => b.data ?? []);

export const listModels = (f: FetchFn) =>
  json<{ data: { name: string }[] }>(f("/api/v1/models")).then((b) => b.data ?? []);

export const upsertModelProvider = (f: FetchFn, manifest: unknown) =>
  f("/api/v1/settings/model-providers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ manifest }),
  });

export const deleteModelProvider = (f: FetchFn, name: string) =>
  f(`/api/v1/settings/model-providers/${encodeURIComponent(name)}`, { method: "DELETE" });

export const listMcpServers = (f: FetchFn) =>
  json<{ data: unknown[] }>(f("/api/v1/settings/mcp-servers")).then((b) => b.data ?? []);

export const upsertMcpServer = (f: FetchFn, manifest: unknown) =>
  f("/api/v1/settings/mcp-servers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ manifest }),
  });

export const deleteMcpServer = (f: FetchFn, name: string) =>
  f(`/api/v1/settings/mcp-servers/${encodeURIComponent(name)}`, { method: "DELETE" });

export const getCapabilities = (f: FetchFn) =>
  json<{ data: { sandbox?: { enabled?: boolean } } }>(f("/api/v1/capabilities")).then((b) => b.data);

export const upsertSandboxProvider = (f: FetchFn, manifest: unknown) =>
  f("/api/v1/settings/sandbox-providers", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ manifest }),
  });

export const registryHealth = (f: FetchFn) =>
  json<{ data: { ok: boolean } }>(f("/api/sf/health")).then((b) => b.data);

export const registrySnapshot = (f: FetchFn) =>
  json<{ data: { mcp_servers: unknown[]; models: string[]; sandbox_enabled: boolean } }>(
    f("/api/sf/snapshot"),
  ).then((b) => b.data);

export const registryApplyAgent = (f: FetchFn, overrides: Record<string, string[]> = {}) =>
  f("/api/sf/apply-agent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ overrides }),
  });

export const registrySetModel = (f: FetchFn, model: string) =>
  f("/api/sf/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ model }),
  });

export const configPostgres = (f: FetchFn, databaseUrl: string) =>
  f("/api/sf/config/postgres-mcp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ database_url: databaseUrl }),
  });

export const configGithub = (f: FetchFn, token: string, defaultRepo: string) =>
  f("/api/sf/config/github-mcp", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, default_repo: defaultRepo }),
  });
