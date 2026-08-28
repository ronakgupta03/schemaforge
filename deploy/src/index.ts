import { Container, ContainerProxy, getContainer } from "@cloudflare/containers";
import { env } from "cloudflare:workers";

// Cloudflare Containers are Workers-only: this Unified Worker serves the SPA
// (via [assets]) and routes /api/* to the TrueForge container. Verified against
// wrangler schema + CF Containers docs (see plan EXECUTION NOTE 2).

export { ContainerProxy };

interface ContainerEnv {
  TRUEFORGE_CONTAINER: DurableObjectNamespace<Container>;
  POSTGRES_MCP_CONTAINER: DurableObjectNamespace<Container>;
  GITHUB_MCP_CONTAINER: DurableObjectNamespace<Container>;
  PUBLIC_BASE_URL: string;
  POSTGRES_USER: string;
  POSTGRES_PASSWORD: string;
  POSTGRES_HOST: string;
  POSTGRES_PORT: string;
  POSTGRES_DB: string;
  REDIS_URL: string;
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
  defaultPort = 8001;
  sleepAfter = "10m";
}

export class GithubMcpContainer extends Container {
  defaultPort = 8002;
  sleepAfter = "10m";
}

interface Env extends ContainerEnv {
  ASSETS: Fetcher;
}

export default {
  async fetch(request: Request, e: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/api/")) {
      const container = getContainerStub(e.TRUEFORGE_CONTAINER, "default");
      return await container.fetch(request);
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