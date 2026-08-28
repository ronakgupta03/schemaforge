import { useEffect, useState, useCallback } from "react";
import type { FetchFn } from "../sfApi";
import {
  listModelProviders,
  listModels,
  upsertModelProvider,
  deleteModelProvider,
  listMcpServers,
  upsertMcpServer,
  deleteMcpServer,
  getCapabilities,
  upsertSandboxProvider,
  registrySnapshot,
  registryApplyAgent,
  registrySetModel,
  configPostgres,
  configGithub,
} from "../settingsApi";

export interface SettingsPanelProps {
  fetchFn?: FetchFn;
}

const RESOURCE_NAME_REGEX = /^[a-z](?:[a-z0-9._-]{0,62}[a-z0-9])?$/;

export function isValidResourceName(name: string): boolean {
  if (!name || name.length > 64) return false;
  return RESOURCE_NAME_REGEX.test(name);
}

export function SettingsPanel({ fetchFn = fetch }: SettingsPanelProps) {
  // State for loaded data
  const [models, setModels] = useState<{ name: string }[]>([]);
  const [modelProviders, setModelProviders] = useState<unknown[]>([]);
  const [mcpServers, setMcpServers] = useState<unknown[]>([]);
  const [capabilities, setCapabilities] = useState<{ sandbox?: { enabled?: boolean } } | undefined>();
  const [snapshot, setSnapshot] = useState<
    { mcp_servers: unknown[]; models: string[]; sandbox_enabled: boolean } | undefined
  >();

  // Form states
  // 1. Models
  const [selectedModel, setSelectedModel] = useState("");
  const [providerName, setProviderName] = useState("");
  const [providerBaseUrl, setProviderBaseUrl] = useState("");
  const [providerApiKey, setProviderApiKey] = useState("");
  const [providerModelId, setProviderModelId] = useState("");
  const [providerModelName, setProviderModelName] = useState("");
  const [modelStatus, setModelStatus] = useState<string | null>(null);

  // 2. Connectors
  const [mcpName, setMcpName] = useState("");
  const [mcpUrl, setMcpUrl] = useState("");
  const [mcpDescription, setMcpDescription] = useState("");
  const [connectorStatus, setConnectorStatus] = useState<string | null>(null);

  // 3. Services
  const [postgresDsn, setPostgresDsn] = useState("");
  const [postgresStatus, setPostgresStatus] = useState<string | null>(null);
  const [githubToken, setGithubToken] = useState("");
  const [githubRepo, setGithubRepo] = useState("");
  const [githubStatus, setGithubStatus] = useState<string | null>(null);

  // 4. Sandbox
  const [daytonaApiKey, setDaytonaApiKey] = useState("");
  const [daytonaExecTimeout, setDaytonaExecTimeout] = useState(300000);
  const [daytonaAutoStop, setDaytonaAutoStop] = useState(true);
  const [daytonaAutoArchive, setDaytonaAutoArchive] = useState(false);
  const [daytonaAutoDelete, setDaytonaAutoDelete] = useState(false);
  const [sandboxStatus, setSandboxStatus] = useState<string | null>(null);

  // 5. Apply Agent
  const [applyResult, setApplyResult] = useState<{
    ok: boolean;
    message: string;
    manifest?: { model?: { name?: string }; [k: string]: unknown };
    omitted?: string[];
  } | null>(null);
  const [isApplying, setIsApplying] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [modelsData, providersData, serversData, capsData, snapData] = await Promise.all([
        listModels(fetchFn).catch(() => []),
        listModelProviders(fetchFn).catch(() => []),
        listMcpServers(fetchFn).catch(() => []),
        getCapabilities(fetchFn).catch(() => undefined),
        registrySnapshot(fetchFn).catch(() => undefined),
      ]);
      setModels(modelsData);
      setModelProviders(providersData);
      setMcpServers(serversData);
      setCapabilities(capsData);
      setSnapshot(snapData);
    } catch {
      // Ignore refresh errors
    }
  }, [fetchFn]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // Model handlers
  const handleSetModel = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedModel) return;
    try {
      const res = await registrySetModel(fetchFn, selectedModel);
      if (res.ok) {
        setModelStatus(`Active model set to ${selectedModel}`);
        refresh();
      } else {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        setModelStatus(`Error: ${body.error || res.statusText}`);
      }
    } catch (err: unknown) {
      setModelStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleAddProvider = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValidResourceName(providerName)) {
      setModelStatus("Invalid provider name: must start with [a-z] and contain only [a-z0-9._-], max 64 chars");
      return;
    }
    const manifest = {
      type: "custom",
      name: providerName,
      base_url: providerBaseUrl,
      auth: { api_key: providerApiKey },
      models: [
        {
          model_id: providerModelId,
          name: providerModelName || providerModelId,
          properties: {},
        },
      ],
    };
    try {
      const res = await upsertModelProvider(fetchFn, manifest);
      if (res.ok) {
        setModelStatus(`Provider "${providerName}" added`);
        setProviderName("");
        setProviderBaseUrl("");
        setProviderApiKey("");
        setProviderModelId("");
        setProviderModelName("");
        refresh();
      } else {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        setModelStatus(`Error: ${body.error || res.statusText}`);
      }
    } catch (err: unknown) {
      setModelStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleDeleteProvider = async (name: string) => {
    try {
      const res = await deleteModelProvider(fetchFn, name);
      if (res.ok) {
        setModelStatus(`Provider "${name}" deleted`);
        refresh();
      } else {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        setModelStatus(`Error deleting: ${body.error || res.statusText}`);
      }
    } catch (err: unknown) {
      setModelStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // Connector handlers
  const handleAddConnector = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!isValidResourceName(mcpName)) {
      setConnectorStatus("Invalid connector name: must start with [a-z] and contain only [a-z0-9._-], max 64 chars");
      return;
    }
    const manifest = {
      type: "remote",
      name: mcpName,
      url: mcpUrl,
      description: mcpDescription,
    };
    try {
      const res = await upsertMcpServer(fetchFn, manifest);
      if (res.ok) {
        setConnectorStatus(`Connector "${mcpName}" registered`);
        setMcpName("");
        setMcpUrl("");
        setMcpDescription("");
        refresh();
      } else {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        setConnectorStatus(`Error: ${body.error || res.statusText}`);
      }
    } catch (err: unknown) {
      setConnectorStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleDeleteConnector = async (name: string) => {
    try {
      const res = await deleteMcpServer(fetchFn, name);
      if (res.ok) {
        setConnectorStatus(`Connector "${name}" removed`);
        refresh();
      } else {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        setConnectorStatus(`Error removing: ${body.error || res.statusText}`);
      }
    } catch (err: unknown) {
      setConnectorStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // Service handlers
  const handleSavePostgres = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await configPostgres(fetchFn, postgresDsn);
      if (res.ok) {
        setPostgresStatus("Postgres DSN saved");
      } else {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        setPostgresStatus(`Error: ${body.error || res.statusText}`);
      }
    } catch (err: unknown) {
      setPostgresStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  const handleSaveGithub = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      const res = await configGithub(fetchFn, githubToken, githubRepo);
      if (res.ok) {
        setGithubStatus("GitHub token & default repo saved");
      } else {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        setGithubStatus(`Error: ${body.error || res.statusText}`);
      }
    } catch (err: unknown) {
      setGithubStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // Sandbox handlers
  const handleSaveSandbox = async (e: React.FormEvent) => {
    e.preventDefault();
    const manifest = {
      type: "daytona",
      auth: { api_key: daytonaApiKey },
      exec_timeout_ms: Number(daytonaExecTimeout),
      // Interval durations in minutes; 0 disables (verified schema).
      auto_stop: daytonaAutoStop ? 30 : 0,
      auto_archive: daytonaAutoArchive ? 1440 : 0,
      auto_delete: daytonaAutoDelete ? 10080 : 0,
    };
    try {
      const res = await upsertSandboxProvider(fetchFn, manifest);
      if (res.ok) {
        setSandboxStatus("Daytona sandbox provider saved");
        refresh();
      } else {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        setSandboxStatus(`Error: ${body.error || res.statusText}`);
      }
    } catch (err: unknown) {
      setSandboxStatus(`Error: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  // Apply Agent handler
  const handleApplyAgent = async () => {
    setIsApplying(true);
    setApplyResult(null);
    try {
      const res = await registryApplyAgent(fetchFn);
      if (res.ok) {
        const body = await res.json();
        const data = body.data || body;
        setApplyResult({
          ok: true,
          message: "Manifest applied successfully",
          manifest: data.manifest,
          omitted: data.omitted,
        });
      } else {
        let errMessage = `${res.status} ${res.statusText}`;
        try {
          const body = await res.json();
          if (body.error) errMessage = body.error;
        } catch {
          const text = await res.text();
          if (text) errMessage = text;
        }
        setApplyResult({
          ok: false,
          message: `Failed to apply agent: ${errMessage}`,
        });
      }
    } catch (err: unknown) {
      setApplyResult({
        ok: false,
        message: `Error applying agent: ${err instanceof Error ? err.message : String(err)}`,
      });
    } finally {
      setIsApplying(false);
    }
  };

  const sandboxEnabled =
    Boolean(capabilities?.sandbox?.enabled) || Boolean(snapshot?.sandbox_enabled);

  return (
    <div className="space-y-6 p-4 text-xs" style={{ color: "var(--sf-text)" }}>
      {/* 1. Models */}
      <section className="rounded border p-3 space-y-3" style={{ borderColor: "var(--sf-border)" }}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Models</h2>
          <span style={{ color: "var(--sf-muted)" }}>
            {models.length} model{models.length === 1 ? "" : "s"} available
          </span>
        </div>

        {/* Display model names */}
        {models.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-medium" style={{ color: "var(--sf-muted)" }}>Available Models:</div>
            <div className="flex flex-wrap gap-1">
              {models.map((m) => (
                <span
                  key={m.name}
                  className="rounded px-2 py-0.5 text-xs font-mono"
                  style={{ background: "var(--sf-bg)", border: "1px solid var(--sf-border)" }}
                >
                  {m.name}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Configured model providers */}
        {modelProviders.length > 0 && (
          <div className="space-y-1">
            <div className="text-xs font-medium" style={{ color: "var(--sf-muted)" }}>Configured Providers:</div>
            {(modelProviders as Array<{ name?: string }>).map((p, idx) => (
              <div
                key={p.name || idx}
                className="flex items-center justify-between rounded border px-2 py-1"
                style={{ borderColor: "var(--sf-border)", background: "var(--sf-bg)" }}
              >
                <span>{p.name}</span>
                {p.name && (
                  <button
                    onClick={() => handleDeleteProvider(p.name!)}
                    className="rounded px-2 py-0.5 text-xs cursor-pointer"
                    style={{ color: "var(--sf-fail)", border: "1px solid var(--sf-border)" }}
                  >
                    Delete
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Active Model Selection */}
        <form onSubmit={handleSetModel} className="flex gap-2 items-center">
          <input
            type="text"
            placeholder="Select or enter active model (e.g. cloudflare/deepseek-v4-flash)"
            value={selectedModel}
            onChange={(e) => setSelectedModel(e.target.value)}
            className="flex-1 rounded border px-2 py-1 text-xs"
            style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
          />
          <button
            type="submit"
            className="rounded px-3 py-1 text-xs font-semibold cursor-pointer"
            style={{ background: "var(--sf-accent)", color: "#0b1220" }}
          >
            Set active model
          </button>
        </form>

        {/* Add Model Provider */}
        <details className="space-y-2 pt-1">
          <summary className="cursor-pointer font-medium" style={{ color: "var(--sf-muted)" }}>
            + Add Custom Model Provider
          </summary>
          <form onSubmit={handleAddProvider} className="space-y-2 pt-2 border-t" style={{ borderColor: "var(--sf-border)" }}>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>Provider Name *</label>
                <input
                  type="text"
                  placeholder="e.g. groq"
                  value={providerName}
                  onChange={(e) => setProviderName(e.target.value)}
                  className="w-full rounded border px-2 py-1 text-xs"
                  style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
                />
              </div>
              <div>
                <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>Base URL *</label>
                <input
                  type="text"
                  placeholder="https://api.groq.com/openai/v1"
                  value={providerBaseUrl}
                  onChange={(e) => setProviderBaseUrl(e.target.value)}
                  className="w-full rounded border px-2 py-1 text-xs"
                  style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
                />
              </div>
              <div>
                <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>API Key</label>
                <input
                  type="password"
                  placeholder="gsk_..."
                  value={providerApiKey}
                  onChange={(e) => setProviderApiKey(e.target.value)}
                  className="w-full rounded border px-2 py-1 text-xs"
                  style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
                />
              </div>
              <div>
                <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>Model ID *</label>
                <input
                  type="text"
                  placeholder="llama-3.3-70b-versatile"
                  value={providerModelId}
                  onChange={(e) => setProviderModelId(e.target.value)}
                  className="w-full rounded border px-2 py-1 text-xs"
                  style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
                />
              </div>
            </div>
            <button
              type="submit"
              className="rounded px-3 py-1 text-xs font-semibold cursor-pointer mt-2"
              style={{ background: "var(--sf-accent)", color: "#0b1220" }}
            >
              Add model provider
            </button>
          </form>
        </details>

        {modelStatus && (
          <div className="text-xs mt-1" style={{ color: modelStatus.startsWith("Error") ? "var(--sf-fail)" : "var(--sf-ok)" }}>
            {modelStatus}
          </div>
        )}
      </section>

      {/* 2. Connectors */}
      <section className="rounded border p-3 space-y-3" style={{ borderColor: "var(--sf-border)" }}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Connectors</h2>
          <span style={{ color: "var(--sf-muted)" }}>
            {mcpServers.length} connector{mcpServers.length === 1 ? "" : "s"}
          </span>
        </div>

        {/* Existing MCP servers */}
        {mcpServers.length > 0 && (
          <div className="space-y-1">
            {(mcpServers as Array<{ name?: string; url?: string; description?: string }>).map((s, idx) => (
              <div
                key={s.name || idx}
                className="flex items-center justify-between rounded border px-2 py-1"
                style={{ borderColor: "var(--sf-border)", background: "var(--sf-bg)" }}
              >
                <div>
                  <span className="font-semibold">{s.name}</span>
                  {s.url && <span className="ml-2 font-mono" style={{ color: "var(--sf-muted)" }}>{s.url}</span>}
                  {s.description && <span className="ml-2 text-[11px]" style={{ color: "var(--sf-muted)" }}>({s.description})</span>}
                </div>
                {s.name && (
                  <button
                    onClick={() => handleDeleteConnector(s.name!)}
                    className="rounded px-2 py-0.5 text-xs cursor-pointer"
                    style={{ color: "var(--sf-fail)", border: "1px solid var(--sf-border)" }}
                  >
                    Delete
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Add Remote MCP Connector */}
        <details className="space-y-2 pt-1">
          <summary className="cursor-pointer font-medium" style={{ color: "var(--sf-muted)" }}>
            + Add MCP Connector
          </summary>
          <form onSubmit={handleAddConnector} className="space-y-2 pt-2 border-t" style={{ borderColor: "var(--sf-border)" }}>
            <div className="grid grid-cols-2 gap-2">
              <div>
                <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>Name *</label>
                <input
                  type="text"
                  placeholder="e.g. postgres-prod"
                  value={mcpName}
                  onChange={(e) => setMcpName(e.target.value)}
                  className="w-full rounded border px-2 py-1 text-xs"
                  style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
                />
              </div>
              <div>
                <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>URL *</label>
                <input
                  type="text"
                  placeholder="http://localhost:8001/mcp"
                  value={mcpUrl}
                  onChange={(e) => setMcpUrl(e.target.value)}
                  className="w-full rounded border px-2 py-1 text-xs"
                  style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
                />
              </div>
              <div className="col-span-2">
                <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>Description</label>
                <input
                  type="text"
                  placeholder="e.g. Production Postgres MCP Server"
                  value={mcpDescription}
                  onChange={(e) => setMcpDescription(e.target.value)}
                  className="w-full rounded border px-2 py-1 text-xs"
                  style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
                />
              </div>
            </div>
            <button
              type="submit"
              className="rounded px-3 py-1 text-xs font-semibold cursor-pointer mt-2"
              style={{ background: "var(--sf-accent)", color: "#0b1220" }}
            >
              Add connector
            </button>
          </form>
        </details>

        {connectorStatus && (
          <div className="text-xs mt-1" style={{ color: connectorStatus.startsWith("Error") ? "var(--sf-fail)" : "var(--sf-ok)" }}>
            {connectorStatus}
          </div>
        )}
      </section>

      {/* 3. Services */}
      <section className="rounded border p-3 space-y-4" style={{ borderColor: "var(--sf-border)" }}>
        <h2 className="text-sm font-semibold">Services</h2>

        {/* Postgres MCP service config */}
        <form onSubmit={handleSavePostgres} className="space-y-2 rounded border p-2.5" style={{ borderColor: "var(--sf-border)", background: "var(--sf-bg)" }}>
          <div className="font-semibold text-xs">Postgres MCP Service</div>
          <div>
            <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>Database URL / DSN</label>
            <input
              type="text"
              placeholder="postgresql://postgres:postgres@127.0.0.1:5432/postgres"
              value={postgresDsn}
              onChange={(e) => setPostgresDsn(e.target.value)}
              className="w-full rounded border px-2 py-1 text-xs font-mono"
              style={{ background: "var(--sf-panel)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
            />
          </div>
          <div className="flex justify-between items-center pt-1">
            <button
              type="submit"
              className="rounded px-3 py-1 text-xs font-semibold cursor-pointer"
              style={{ background: "var(--sf-accent)", color: "#0b1220" }}
            >
              Save Postgres config
            </button>
            {postgresStatus && (
              <span className="text-xs" style={{ color: postgresStatus.startsWith("Error") ? "var(--sf-fail)" : "var(--sf-ok)" }}>
                {postgresStatus}
              </span>
            )}
          </div>
        </form>

        {/* GitHub MCP service config */}
        <form onSubmit={handleSaveGithub} className="space-y-2 rounded border p-2.5" style={{ borderColor: "var(--sf-border)", background: "var(--sf-bg)" }}>
          <div className="font-semibold text-xs">GitHub MCP Service</div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>GitHub Token</label>
              <input
                type="password"
                placeholder="ghp_..."
                value={githubToken}
                onChange={(e) => setGithubToken(e.target.value)}
                className="w-full rounded border px-2 py-1 text-xs"
                style={{ background: "var(--sf-panel)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
              />
            </div>
            <div>
              <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>Default Repo</label>
              <input
                type="text"
                placeholder="owner/repo"
                value={githubRepo}
                onChange={(e) => setGithubRepo(e.target.value)}
                className="w-full rounded border px-2 py-1 text-xs font-mono"
                style={{ background: "var(--sf-panel)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
              />
            </div>
          </div>
          <div className="flex justify-between items-center pt-1">
            <button
              type="submit"
              className="rounded px-3 py-1 text-xs font-semibold cursor-pointer"
              style={{ background: "var(--sf-accent)", color: "#0b1220" }}
            >
              Save GitHub config
            </button>
            {githubStatus && (
              <span className="text-xs" style={{ color: githubStatus.startsWith("Error") ? "var(--sf-fail)" : "var(--sf-ok)" }}>
                {githubStatus}
              </span>
            )}
          </div>
        </form>
      </section>

      {/* 4. Sandbox */}
      <section className="rounded border p-3 space-y-3" style={{ borderColor: "var(--sf-border)" }}>
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Sandbox</h2>
          <span
            className="rounded px-2 py-0.5 text-xs font-semibold"
            style={{
              background: sandboxEnabled ? "rgba(52, 211, 153, 0.15)" : "rgba(248, 113, 113, 0.15)",
              color: sandboxEnabled ? "var(--sf-ok)" : "var(--sf-fail)",
            }}
          >
            {sandboxEnabled ? "Enabled" : "Disabled"}
          </span>
        </div>

        <form onSubmit={handleSaveSandbox} className="space-y-3">
          <div>
            <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>Daytona API Key</label>
            <input
              type="password"
              placeholder="dapi_..."
              value={daytonaApiKey}
              onChange={(e) => setDaytonaApiKey(e.target.value)}
              className="w-full rounded border px-2 py-1 text-xs"
              style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="block mb-1 text-[11px]" style={{ color: "var(--sf-muted)" }}>Exec Timeout (ms)</label>
              <input
                type="number"
                value={daytonaExecTimeout}
                onChange={(e) => setDaytonaExecTimeout(Number(e.target.value))}
                className="w-full rounded border px-2 py-1 text-xs"
                style={{ background: "var(--sf-bg)", borderColor: "var(--sf-border)", color: "var(--sf-text)" }}
              />
            </div>
            <div className="flex flex-col justify-end gap-1">
              <label className="flex items-center gap-1 text-[11px]">
                <input
                  type="checkbox"
                  checked={daytonaAutoStop}
                  onChange={(e) => setDaytonaAutoStop(e.target.checked)}
                />
                Auto Stop
              </label>
              <label className="flex items-center gap-1 text-[11px]">
                <input
                  type="checkbox"
                  checked={daytonaAutoArchive}
                  onChange={(e) => setDaytonaAutoArchive(e.target.checked)}
                />
                Auto Archive
              </label>
            </div>
            <div className="flex flex-col justify-end gap-1">
              <label className="flex items-center gap-1 text-[11px]">
                <input
                  type="checkbox"
                  checked={daytonaAutoDelete}
                  onChange={(e) => setDaytonaAutoDelete(e.target.checked)}
                />
                Auto Delete
              </label>
            </div>
          </div>
          <div className="flex justify-between items-center pt-1">
            <button
              type="submit"
              className="rounded px-3 py-1 text-xs font-semibold cursor-pointer"
              style={{ background: "var(--sf-accent)", color: "#0b1220" }}
            >
              Save Daytona config
            </button>
            {sandboxStatus && (
              <span className="text-xs" style={{ color: sandboxStatus.startsWith("Error") ? "var(--sf-fail)" : "var(--sf-ok)" }}>
                {sandboxStatus}
              </span>
            )}
          </div>
        </form>
      </section>

      {/* 5. Apply agent */}
      <section className="rounded border p-3 space-y-3" style={{ borderColor: "var(--sf-border)" }}>
        <h2 className="text-sm font-semibold">Apply agent</h2>
        <p className="text-xs" style={{ color: "var(--sf-muted)" }}>
          Derive and apply the SchemaForge agent manifest from the current settings (models, connectors, and sandbox).
        </p>

        <button
          onClick={handleApplyAgent}
          disabled={isApplying}
          className="rounded px-4 py-2 text-xs font-semibold cursor-pointer"
          style={{
            background: "var(--sf-accent)",
            color: "#0b1220",
            opacity: isApplying ? 0.7 : 1,
          }}
        >
          {isApplying ? "Applying agent…" : "Save & apply agent"}
        </button>

        {applyResult && (
          <div
            className="rounded border p-2.5 text-xs space-y-1"
            style={{
              borderColor: applyResult.ok ? "var(--sf-ok)" : "var(--sf-fail)",
              background: "var(--sf-bg)",
            }}
          >
            <div className="font-semibold" style={{ color: applyResult.ok ? "var(--sf-ok)" : "var(--sf-fail)" }}>
              {applyResult.ok ? "Agent manifest applied successfully." : applyResult.message}
            </div>
            {applyResult.ok && applyResult.manifest ? (
              <div className="space-y-1 pt-1">
                <div>
                  <span style={{ color: "var(--sf-muted)" }}>Model: </span>
                  <span className="font-mono">{applyResult.manifest.model?.name ?? "default"}</span>
                </div>
                {applyResult.omitted && applyResult.omitted.length > 0 && (
                  <div>
                    <span style={{ color: "var(--sf-muted)" }}>Omitted unconfigured connectors: </span>
                    <span>{applyResult.omitted.join(", ")}</span>
                  </div>
                )}
                <details className="pt-1">
                  <summary className="cursor-pointer text-[11px]" style={{ color: "var(--sf-muted)" }}>
                    View full manifest JSON
                  </summary>
                  <pre className="mt-1 rounded p-2 overflow-auto text-[11px] whitespace-pre-wrap" style={{ background: "var(--sf-panel)" }}>
                    {JSON.stringify(applyResult.manifest, null, 2)}
                  </pre>
                </details>
              </div>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
