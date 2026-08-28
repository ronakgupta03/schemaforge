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
  PUBLIC_BASE_URL: string;
  POSTGRES_USER: string;
  POSTGRES_PASSWORD: string;
  POSTGRES_HOST: string;
  POSTGRES_PORT: string;
  POSTGRES_DB: string;
  REDIS_URL: string;
  SF_MCP_CONFIG_TOKEN: string;
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
    SF_MCP_CONFIG_TOKEN: runtimeEnv.SF_MCP_CONFIG_TOKEN,
    SF_CONFIG_PORT: "9001",
    PORT: "80",
  };
}

export class GithubMcpContainer extends Container {
  defaultPort = 80; // outbound interception is HTTP(S) 80/443 only
  sleepAfter = "10m";

  envVars = {
    SF_MCP_CONFIG_TOKEN: runtimeEnv.SF_MCP_CONFIG_TOKEN,
    SF_CONFIG_PORT: "9002",
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

export default {
  async fetch(request: Request, e: Env): Promise<Response> {
    const url = new URL(request.url);
    const p = url.pathname;

    if (p === "/api/sf/config/postgres-mcp" || p.startsWith("/api/sf/config/postgres-mcp/")) {
      const container = getContainerStub(e.POSTGRES_MCP_CONTAINER, "default");
      const subpath = p.slice("/api/sf/config/postgres-mcp".length) || "/config";
      const targetUrl = new URL(subpath + url.search, url);
      return await container.fetch(
        switchPort(new Request(targetUrl.toString(), request), 9001),
      );
    }

    if (p === "/api/sf/config/github-mcp" || p.startsWith("/api/sf/config/github-mcp/")) {
      const container = getContainerStub(e.GITHUB_MCP_CONTAINER, "default");
      const subpath = p.slice("/api/sf/config/github-mcp".length) || "/config";
      const targetUrl = new URL(subpath + url.search, url);
      return await container.fetch(
        switchPort(new Request(targetUrl.toString(), request), 9002),
      );
    }

    if (p === "/api/sf" || p.startsWith("/api/sf/")) {
      const container = getContainerStub(e.REGISTRY_CONTAINER, "default");
      const subpath = p.slice("/api/sf".length) || "/";
      const targetUrl = new URL(subpath + url.search, url);
      return await container.fetch(
        new Request(targetUrl.toString(), request),
      );
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
