#!/usr/bin/env node
// SchemaForge local stack: TrueForge + postgres-mcp + github-mcp + registry + UI.
import { spawn } from "node:child_process";
import { createServer, request as httpRequest } from "node:http";
import { createReadStream, existsSync, statSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { once } from "node:events";

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const PKG_ROOT = join(__dirname, "..");
const REPO_ROOT = join(PKG_ROOT, "..", "..");
const ROOT = existsSync(join(PKG_ROOT, "core"))
  ? PKG_ROOT
  : existsSync(join(REPO_ROOT, "core"))
  ? REPO_ROOT
  : PKG_ROOT;
const DIST = existsSync(join(PKG_ROOT, "ui-dist"))
  ? join(PKG_ROOT, "ui-dist")
  : existsSync(join(REPO_ROOT, "packages", "cli", "ui-dist"))
  ? join(REPO_ROOT, "packages", "cli", "ui-dist")
  : existsSync(join(REPO_ROOT, "ui", "dist"))
  ? join(REPO_ROOT, "ui", "dist")
  : join(PKG_ROOT, "ui-dist");

const args = process.argv.slice(2);
const noOpen = args.includes("--no-open");

let uiPort = 5173;
const portIdx = args.indexOf("--port");
if (portIdx !== -1 && args[portIdx + 1]) {
  uiPort = Number(args[portIdx + 1]) || 5173;
}

let stateDir = process.env.SF_STATE_DIR || join(process.env.HOME || process.env.USERPROFILE || ".", ".schemaforge");
const stateDirIdx = args.indexOf("--state-dir");
if (stateDirIdx !== -1 && args[stateDirIdx + 1]) {
  stateDir = args[stateDirIdx + 1];
}

const py = process.env.SF_PYTHON || "python3";
const tfPort = process.env.TRUEFORGE_PORT || "8790";
const tfHost = process.env.TRUEFORGE_HOST || "127.0.0.1";
const pgConfigPort = process.env.SF_POSTGRES_CONFIG_PORT || "9001";
const ghConfigPort = process.env.SF_GITHUB_CONFIG_PORT || "9002";
const pgTransportPort = process.env.SF_POSTGRES_PORT || "8001";
const ghTransportPort = process.env.SF_GITHUB_PORT || "8002";
const regPort = process.env.SF_REGISTRY_PORT || "9010";

const kids = [];
let shuttingDown = false;

function cleanupAndExit(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const k of kids) {
    try {
      k.kill("SIGTERM");
    } catch {
      // ignore
    }
  }
  setTimeout(() => {
    for (const k of kids) {
      try {
        k.kill("SIGKILL");
      } catch {
        // ignore
      }
    }
    process.exit(code);
  }, 2000).unref();
  process.exit(code);
}

process.on("SIGINT", () => cleanupAndExit(0));
process.on("SIGTERM", () => cleanupAndExit(0));
process.on("exit", () => {
  for (const k of kids) {
    try {
      k.kill("SIGTERM");
    } catch {
      // ignore
    }
  }
});

function start(cmd, argv = [], env = {}) {
  const p = spawn(cmd, argv, {
    cwd: ROOT,
    env: {
      ...process.env,
      SF_STATE_DIR: stateDir,
      ...env,
    },
    shell: false,
    stdio: ["ignore", "inherit", "inherit"],
  });
  kids.push(p);
  p.on("exit", (code, signal) => {
    if (code !== 0 && code !== null && !shuttingDown) {
      console.warn(`[schemaforge] child process (${cmd}) exited with code ${code}`);
    }
  });
  return p;
}

// 1. venv bootstrap (first run)
const venvDir = join(stateDir, ".sfenv");
const isWin = process.platform === "win32";
const venvPy = isWin ? join(venvDir, "Scripts", "python.exe") : join(venvDir, "bin", "python");
const venvPip = isWin ? join(venvDir, "Scripts", "pip.exe") : join(venvDir, "bin", "pip");
const venvReady = join(venvDir, ".ready");

if (!existsSync(venvReady)) {
  console.log(`[schemaforge] bootstrapping python venv at ${venvDir}`);
  if (existsSync(venvDir)) {
    rmSync(venvDir, { recursive: true, force: true });
  }
  mkdirSync(stateDir, { recursive: true });
  const venvProc = spawn(py, ["-m", "venv", venvDir], { stdio: "inherit" });
  const [venvExit] = await once(venvProc, "exit");
  if (venvExit !== 0) {
    console.error(`[schemaforge] failed to create venv (exit code ${venvExit})`);
    process.exit(1);
  }

  const pipArgs = ["install", "-q", "-e", join(ROOT, "core")];
  const pgReq = join(ROOT, "mcp-servers", "postgres-mcp", "requirements.txt");
  if (existsSync(pgReq)) {
    pipArgs.push("-r", pgReq);
  }
  const ghReq = join(ROOT, "mcp-servers", "github-mcp", "requirements.txt");
  if (existsSync(ghReq)) {
    pipArgs.push("-r", ghReq);
  }

  const pipProc = spawn(venvPip, pipArgs, { stdio: "inherit" });
  const [pipExit] = await once(pipProc, "exit");
  if (pipExit !== 0) {
    console.error(`[schemaforge] failed to install dependencies (exit code ${pipExit})`);
    process.exit(1);
  }

  writeFileSync(venvReady, "ok");
  console.log("[schemaforge] venv bootstrap complete");
}

// 2. services
start(venvPy, [join(ROOT, "mcp-servers", "postgres-mcp", "server.py")], {
  SF_CONFIG_PORT: pgConfigPort,
  PORT: pgTransportPort,
  DATABASE_URL: process.env.DATABASE_URL || "",
});

start(venvPy, [join(ROOT, "mcp-servers", "github-mcp", "server.py")], {
  SF_CONFIG_PORT: ghConfigPort,
  PORT: ghTransportPort,
  GITHUB_PERSONAL_ACCESS_TOKEN: process.env.GITHUB_PERSONAL_ACCESS_TOKEN || "",
});

const regServerFile = join(ROOT, "core", "schemaforge_core", "registry_server.py");
if (existsSync(regServerFile)) {
  start(venvPy, ["-m", "schemaforge_core.registry_server"], {
    SF_REGISTRY_PORT: regPort,
    TRUEFORGE_URL: `http://localhost:${tfPort}`,
  });
} else {
  const inlineRegistryPy = `
import json, os
from http.server import HTTPServer, BaseHTTPRequestHandler

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass
    def do_GET(self):
        if self.path == '/health':
            body = json.dumps({'data': {'ok': True}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == '/snapshot':
            body = json.dumps({'data': {'mcp_servers': [], 'models': [], 'sandbox_enabled': False}}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

port = int(os.environ.get('SF_REGISTRY_PORT', '9010'))
HTTPServer(('127.0.0.1', port), Handler).serve_forever()
`;
  start(venvPy, ["-c", inlineRegistryPy], {
    SF_REGISTRY_PORT: regPort,
    TRUEFORGE_URL: `http://localhost:${tfPort}`,
  });
}

// 3. TrueForge (standalone)
start("npx", ["@truefoundry/trueforge"], {
  STANDALONE: "true",
  PORT: tfPort,
  HOST: tfHost,
});

// 4. static UI + proxy
function getProxyTarget(urlPath) {
  const [pathname, search = ""] = urlPath.split("?");
  const query = search ? `?${search}` : "";

  if (pathname === "/api/sf/config/postgres-mcp" || pathname.startsWith("/api/sf/config/postgres-mcp/")) {
    const subpath = pathname.slice("/api/sf/config/postgres-mcp".length) || "";
    return {
      host: "127.0.0.1",
      port: Number(pgConfigPort),
      path: (subpath || "/config") + query,
    };
  }

  if (pathname === "/api/sf/config/github-mcp" || pathname.startsWith("/api/sf/config/github-mcp/")) {
    const subpath = pathname.slice("/api/sf/config/github-mcp".length) || "";
    return {
      host: "127.0.0.1",
      port: Number(ghConfigPort),
      path: (subpath || "/config") + query,
    };
  }

  if (pathname === "/api/sf" || pathname.startsWith("/api/sf/")) {
    const subpath = pathname.slice("/api/sf".length) || "/";
    return {
      host: "127.0.0.1",
      port: Number(regPort),
      path: subpath + query,
    };
  }

  if (pathname === "/api" || pathname.startsWith("/api/")) {
    return {
      host: "::1",
      port: Number(tfPort),
      path: pathname + query,
    };
  }

  return null;
}

const MIME = {
  ".html": "text/html",
  ".js": "text/javascript",
  ".css": "text/css",
  ".json": "application/json",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
  ".woff": "font/woff",
  ".ttf": "font/ttf",
  ".map": "application/json",
  ".txt": "text/plain",
};

const server = createServer((req, res) => {
  const target = getProxyTarget(req.url || "/");
  if (target) {
    const headers = { ...req.headers };
    const hostFormatted = target.host.includes(":") && !target.host.startsWith("[")
      ? `[${target.host}]`
      : target.host;
    headers.host = `${hostFormatted}:${target.port}`;

    const proxyReq = httpRequest(
      {
        host: target.host,
        port: target.port,
        path: target.path,
        method: req.method,
        headers: headers,
      },
      (proxyRes) => {
        res.writeHead(proxyRes.statusCode || 502, proxyRes.headers);
        proxyRes.pipe(res);
      }
    );

    proxyReq.on("error", (err) => {
      if (!res.headersSent) {
        res.writeHead(502, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: `Bad Gateway: ${err.message}` }));
      }
    });

    req.pipe(proxyReq);
    return;
  }

  let reqPath = decodeURIComponent((req.url || "/").split("?")[0]);
  let filePath = normalize(join(DIST, reqPath === "/" ? "index.html" : reqPath));

  if (!filePath.startsWith(DIST)) {
    res.writeHead(403, { "Content-Type": "text/plain" });
    res.end("Forbidden");
  } else {
    if (!existsSync(filePath) || statSync(filePath).isDirectory()) {
      filePath = join(DIST, "index.html");
    }

    if (!existsSync(filePath)) {
      res.writeHead(404, { "Content-Type": "text/plain" });
      res.end("UI not built. Run 'npm run build' in ui/ or build the package.");
    } else {
      const ext = extname(filePath).toLowerCase();
      const contentType = MIME[ext] || "application/octet-stream";
      res.writeHead(200, { "Content-Type": contentType });
      createReadStream(filePath).pipe(res);
    }
  }
});

server.listen(uiPort, "127.0.0.1", () => {
  console.log(`[schemaforge] UI at http://localhost:${uiPort} (TrueForge ${tfPort}, registry ${regPort}, mcp ${pgTransportPort}/${ghTransportPort})`);
  if (!noOpen) {
    if (process.platform === "darwin") {
      spawn("open", [`http://localhost:${uiPort}`], { stdio: "ignore" }).on("error", () => {});
    } else if (process.platform === "win32") {
      spawn("cmd.exe", ["/c", "start", `http://localhost:${uiPort}`], { stdio: "ignore" }).on("error", () => {});
    } else {
      spawn("xdg-open", [`http://localhost:${uiPort}`], { stdio: "ignore" }).on("error", () => {});
    }
  }
});
