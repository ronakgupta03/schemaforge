import { Container, ContainerProxy, getContainer, switchPort } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

// Cloudflare Containers are Workers-only: this Unified Worker serves the SPA
// (via [assets]) and routes /api/* and /tf/* to the TrueForge container,
// /api/sf/* to the registry and MCP config endpoints.
// Verified against wrangler schema + CF Containers docs (plan EXECUTION NOTE 2).
//
// Routing:
//   /api/sf/config/postgres-mcp -> PostgresMcpContainer config port (9001)
//   /api/sf/config/github-mcp   -> GithubMcpContainer config port (9002)
//   /api/sf/*                   -> RegistryContainer (9010)
//   /tf/*                       -> TrueForge container (embedded chat UI)
//   /assets/*                   -> TrueForge container (chat UI assets)
//   /monacoeditorwork/*         -> TrueForge container (Monaco workers)
//   /api/*                      -> TrueForge container (API + SSE)
//   everything else             -> SPA assets (ui/dist)

export { ContainerProxy };

interface ContainerEnv {
  TRUEFORGE_CONTAINER: DurableObjectNamespace<Container>;
  POSTGRES_MCP_CONTAINER: DurableObjectNamespace<Container>;
  GITHUB_MCP_CONTAINER: DurableObjectNamespace<Container>;
  REGISTRY_CONTAINER: DurableObjectNamespace<Container>;
  SF_CONFIG_KV?: KVNamespace;
  PUBLIC_BASE_URL: string;
  POSTGRES_USER: string;
  POSTGRES_PASSWORD: string;
  POSTGRES_HOST: string;
  POSTGRES_PORT: string;
  POSTGRES_DB: string;
  REDIS_URL: string;
  SF_MCP_CONFIG_TOKEN: string;
  SF_DEPLOY_TOKEN?: string;
  DAYTONA_API_KEY?: string;
  ASSETS: Fetcher;
}


// The `cloudflare:workers` env global is untyped; read through a typed lens.
const runtimeEnv = env as unknown as ContainerEnv;

type TypedNamespace = DurableObjectNamespace<Container>;

function getContainerStub(binding: TypedNamespace, id: string) {
  return getContainer(binding as TypedNamespace, id);
}

export class TrueForgeContainer extends Container {
  defaultPort = 8790;
  sleepAfter = "10m";

  envVars = {
    STANDALONE: "false",
    HOST: "0.0.0.0",
    PORT: "8790",
    PUBLIC_BASE_URL: runtimeEnv.PUBLIC_BASE_URL,
    POSTGRES_USER: runtimeEnv.POSTGRES_USER,
    POSTGRES_PASSWORD: runtimeEnv.POSTGRES_PASSWORD,
    POSTGRES_HOST: runtimeEnv.POSTGRES_HOST,
    POSTGRES_PORT: runtimeEnv.POSTGRES_PORT,
    POSTGRES_DB: runtimeEnv.POSTGRES_DB,
    REDIS_URL: runtimeEnv.REDIS_URL,
    DAYTONA_API_KEY: runtimeEnv.DAYTONA_API_KEY ?? "",
  };

  override async onActivityExpired() {
    // Keep-warm: do NOT stop on idle — the demo stack must answer immediately.
    console.log("[TrueForgeContainer] idle timer expired; staying warm");
  }
}

TrueForgeContainer.outboundByHost = {
  "postgres-mcp.internal": async (request: Request, e: unknown) => {
    const target = getContainerStub(
      (e as ContainerEnv).POSTGRES_MCP_CONTAINER,
      "default",
    );
    return target.fetch(request);
  },
  "github-mcp.internal": async (request: Request, e: unknown) => {
    const target = getContainerStub(
      (e as ContainerEnv).GITHUB_MCP_CONTAINER,
      "default",
    );
    return target.fetch(request);
  },
};

export class PostgresMcpContainer extends Container {
  defaultPort = 80; // outbound interception is HTTP(S) 80/443 only
  sleepAfter = "10m";

  envVars = {
    SF_CONFIG_HOST: "0.0.0.0",
    SF_CONFIG_PORT: "9001",
    SF_MCP_CONFIG_TOKEN: runtimeEnv.SF_MCP_CONFIG_TOKEN,
    PORT: "80",
  };
}

export class GithubMcpContainer extends Container {
  defaultPort = 80; // outbound interception is HTTP(S) 80/443 only
  sleepAfter = "10m";

  envVars = {
    SF_CONFIG_HOST: "0.0.0.0",
    SF_CONFIG_PORT: "9002",
    SF_MCP_CONFIG_TOKEN: runtimeEnv.SF_MCP_CONFIG_TOKEN,
    PORT: "80",
  };
}

export class RegistryContainer extends Container {
  defaultPort = 9010;
  sleepAfter = "10m";

  envVars = {
    TRUEFORGE_URL: "http://trueforge.internal",
    SF_REGISTRY_PORT: "9010",
    SF_REGISTRY_HOST: "0.0.0.0",
    SF_AGENT_DIR: "/srv/agent",
  };
}

RegistryContainer.outboundByHost = {
  "trueforge.internal": async (request: Request, e: unknown) => {
    const target = getContainerStub(
      (e as ContainerEnv).TRUEFORGE_CONTAINER,
      "default",
    );
    return target.fetch(request);
  },
};

interface Env extends ContainerEnv {
  ASSETS: Fetcher;
}

const REPLAY_PATHS: Record<string, number> = {
  "/api/sf/config/postgres-mcp": 9001,
  "/api/sf/config/github-mcp": 9002,
  "/api/sf/config": 9010,
  "/api/sf/apply-agent": 9010,
};

let replayPromise: Promise<void> | null = null;
let lastReplay = 0;

async function maybeReplay(e: Env): Promise<void> {
  const now = Date.now();
  if (replayPromise) return replayPromise;
  if (now - lastReplay < 10 * 60 * 1000) return;
  replayPromise = (async () => {
    try {
      if (e.SF_CONFIG_KV) {
        const list = await e.SF_CONFIG_KV.list();
        for (const key of list.keys) {
          try {
            const body = await e.SF_CONFIG_KV.get(key.name);
            const port = REPLAY_PATHS[key.name];
            if (!body || !port) continue;
            const headers: Record<string, string> = { "Content-Type": "application/json" };
            if (key.name.startsWith("/api/sf/config/") && e.SF_MCP_CONFIG_TOKEN) {
              headers["Authorization"] = `Bearer ${e.SF_MCP_CONFIG_TOKEN}`;
            }
            await containerFetch(e, `http://x.internal${key.name}`, { method: "POST", headers, body }, port);
          } catch (itemErr) {
            console.error(`kv replay failed for ${key.name}`, itemErr);
          }
        }
      }
      lastReplay = Date.now();
    } catch (err) {
      console.error("kv replay failed", err);
    } finally {
      replayPromise = null;
    }
  })();
  return replayPromise;
}

async function containerFetch(
  e: Env,
  urlStr: string,
  init: RequestInit,
  port: number,
): Promise<Response> {
  const u = new URL(urlStr);
  const path = u.pathname;
  if (port === 9001) {
    const container = getContainerStub(e.POSTGRES_MCP_CONTAINER, "default");
    const subpath = path.slice("/api/sf/config/postgres-mcp".length) || "/config";
    const req = new Request(new URL(subpath + u.search, "http://postgres-mcp.internal").toString(), init);
    return await container.fetch(switchPort(req, 9001));
  }
  if (port === 9002) {
    const container = getContainerStub(e.GITHUB_MCP_CONTAINER, "default");
    const subpath = path.slice("/api/sf/config/github-mcp".length) || "/config";
    const req = new Request(new URL(subpath + u.search, "http://github-mcp.internal").toString(), init);
    return await container.fetch(switchPort(req, 9002));
  }
  if (port === 9010) {
    const container = getContainerStub(e.REGISTRY_CONTAINER, "default");
    const subpath = path.startsWith("/api/sf") ? (path.slice("/api/sf".length) || "/") : path;
    const req = new Request(new URL(subpath + u.search, "http://registry.internal").toString(), init);
    return await container.fetch(switchPort(req, 9010));
  }
  throw new Error(`Unknown container port: ${port}`);
}

export default {
  async fetch(request: Request, e: Env): Promise<Response> {
    const url = new URL(request.url);
    const p = url.pathname;

    if (e.SF_DEPLOY_TOKEN) {
      const isProtected =
        p.startsWith("/api/v1/settings/") ||
        p === "/api/sf" ||
        p.startsWith("/api/sf/");
      if (isProtected) {
        const viaAccess = request.headers.get("CF-Access-Jwt-Assertion");
        if (!viaAccess) {
          const auth = request.headers.get("Authorization");
          if (auth !== `Bearer ${e.SF_DEPLOY_TOKEN}`) {
            return new Response(JSON.stringify({ error: "Unauthorized" }), {
              status: 401,
              headers: { "Content-Type": "application/json" },
            });
          }
        }
      }
    }

    if (p === "/api/sf" || p.startsWith("/api/sf/")) {
      await maybeReplay(e);
    }

    let replayBody: string | null = null;
    if (request.method === "POST" && p in REPLAY_PATHS) {
      try {
        replayBody = await request.clone().text();
      } catch (err) {
        console.error("Failed to read POST body for replay cache:", err);
      }
    }

    if (p === "/api/sf/config/postgres-mcp" || p.startsWith("/api/sf/config/postgres-mcp/")) {
      const container = getContainerStub(e.POSTGRES_MCP_CONTAINER, "default");
      const subpath = p.slice("/api/sf/config/postgres-mcp".length) || "/config";
      const targetUrl = new URL(subpath + url.search, url);
      const req = new Request(targetUrl.toString(), request);
      if (e.SF_MCP_CONFIG_TOKEN) {
        req.headers.set("Authorization", `Bearer ${e.SF_MCP_CONFIG_TOKEN}`);
      }
      const res = await container.fetch(
        switchPort(req, 9001),
      );
      if (replayBody !== null && res.status < 400 && e.SF_CONFIG_KV) {
        try {
          await e.SF_CONFIG_KV.put(p, replayBody);
        } catch (err) {
          console.error("Failed to persist to SF_CONFIG_KV:", err);
        }
      }
      return res;
    }

    if (p === "/api/sf/config/github-mcp" || p.startsWith("/api/sf/config/github-mcp/")) {
      const container = getContainerStub(e.GITHUB_MCP_CONTAINER, "default");
      const subpath = p.slice("/api/sf/config/github-mcp".length) || "/config";
      const targetUrl = new URL(subpath + url.search, url);
      const req = new Request(targetUrl.toString(), request);
      if (e.SF_MCP_CONFIG_TOKEN) {
        req.headers.set("Authorization", `Bearer ${e.SF_MCP_CONFIG_TOKEN}`);
      }
      const res = await container.fetch(
        switchPort(req, 9002),
      );
      if (replayBody !== null && res.status < 400 && e.SF_CONFIG_KV) {
        try {
          await e.SF_CONFIG_KV.put(p, replayBody);
        } catch (err) {
          console.error("Failed to persist to SF_CONFIG_KV:", err);
        }
      }
      return res;
    }

    if (p === "/api/sf" || p.startsWith("/api/sf/")) {
      const container = getContainerStub(e.REGISTRY_CONTAINER, "default");
      const subpath = p.slice("/api/sf".length) || "/";
      const targetUrl = new URL(subpath + url.search, url);
      const res = await container.fetch(
        new Request(targetUrl.toString(), request),
      );
      if (replayBody !== null && res.status < 400 && e.SF_CONFIG_KV) {
        try {
          await e.SF_CONFIG_KV.put(p, replayBody);
        } catch (err) {
          console.error("Failed to persist to SF_CONFIG_KV:", err);
        }
      }
      return res;
    }

    const isTf =
      p === "/tf" || p.startsWith("/tf/") ||
      p.startsWith("/assets/") || p.startsWith("/monacoeditorwork/") ||
      p.startsWith("/api/");
    if (isTf) {
      const container = getContainerStub(e.TRUEFORGE_CONTAINER, "default");
      // Strip the /tf prefix for the container's own routing; pass through
      // everything else (assets, api) untouched.
      const target = p.startsWith("/tf")
        ? new URL((p === "/tf" ? "/" : p.slice(3)) + url.search, url)
        : url;
      return await container.fetch(
        new Request(target.toString(), request),
      );
    }
    return e.ASSETS.fetch(request);
  },

  async scheduled(controller: ScheduledController, e: Env): Promise<void> {
    // Keep-warm ping every 5 min (belt and braces alongside onActivityExpired).
    const container = getContainerStub(e.TRUEFORGE_CONTAINER, "default");
    try {
      await container.fetch(new Request("https://schemaforge-worker.local/api/v1/capabilities"));
    } catch {
      /* keep-warm ping best-effort */
    }
  },
} satisfies ExportedHandler<Env>;
