#!/usr/bin/env node
// SchemaForge local stack: TrueForge + postgres-mcp + github-mcp + registry + UI.
import { randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { createServer, request as httpRequest } from "node:http";
import { createReadStream, existsSync, statSync, mkdirSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { join, dirname, extname, normalize } from "node:path";
import { fileURLToPath } from "node:url";

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

const instructionsPath = existsSync(join(ROOT, "agent", "instructions.md"))
  ? join(ROOT, "agent", "instructions.md")
  : existsSync(join(REPO_ROOT, "agent", "instructions.md"))
  ? join(REPO_ROOT, "agent", "instructions.md")
  : join(PKG_ROOT, "agent", "instructions.md");

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
const tfHost = process.env.TRUEFORGE_HOST || "::1";
const pgConfigPort = process.env.SF_POSTGRES_CONFIG_PORT || "9001";
const ghConfigPort = process.env.SF_GITHUB_CONFIG_PORT || "9002";
const pgTransportPort = process.env.SF_POSTGRES_PORT || "8001";
const ghTransportPort = process.env.SF_GITHUB_PORT || "8002";
const regPort = process.env.SF_REGISTRY_PORT || "9010";
const configToken = process.env.SF_MCP_CONFIG_TOKEN || randomBytes(24).toString("hex");
const tokenFile = join(stateDir, "sf-mcp-token");
try {
  mkdirSync(stateDir, { recursive: true });
  writeFileSync(tokenFile, configToken, { mode: 0o600 });
} catch (err) {
  console.warn(`[schemaforge] failed to write config token file at ${tokenFile}: ${err.message}`);
}

const kids = [];
let shuttingDown = false;
let server = null;

function httpProbe(host, port, path = "/", timeoutMs = 800, headers = {}) {
  return new Promise((resolve) => {
    const isIpv6 = host.includes(":") && !host.startsWith("[");
    const formattedHost = isIpv6 ? `[${host}]` : host;
    const req = httpRequest(
      {
        host,
        port: Number(port),
        path,
        method: "GET",
        headers: {
          Host: `${formattedHost}:${port}`,
          ...headers,
        },
      },
      (res) => {
        const code = res.statusCode || 0;
        res.resume();
        resolve(code);
      }
    );
    req.setTimeout(timeoutMs, () => {
      req.destroy();
      resolve(0);
    });
    req.on("error", () => {
      resolve(0);
    });
    req.end();
  });
}

function spawnAwait(cmd, argv = [], options = {}) {
  const isWin = process.platform === "win32";
  return new Promise((resolve, reject) => {
    let p;
    try {
      p = spawn(cmd, argv, { shell: isWin, ...options });
    } catch (err) {
      return reject(err);
    }
    p.on("error", (err) => reject(err));
    p.on("exit", (code, signal) => {
      resolve(code ?? (signal ? 1 : 0));
    });
  });
}

function cleanupAndExit(code = 0) {
  if (shuttingDown) return;
  shuttingDown = true;

  if (server) {
    try {
      server.close();
    } catch {
      // ignore
    }
  }

  for (const k of kids) {
    try {
      k.kill("SIGTERM");
    } catch {
      // ignore
    }
  }

  const timer = setTimeout(() => {
    for (const k of kids) {
      try {
        k.kill("SIGKILL");
      } catch {
        // ignore
      }
    }
    process.exit(code);
  }, 2000);
  timer.unref();

  let pending = kids.length;
  if (pending === 0) {
    clearTimeout(timer);
    process.exit(code);
  }
  for (const k of kids) {
    k.on("exit", () => {
      pending--;
      if (pending <= 0) {
        clearTimeout(timer);
        process.exit(code);
      }
    });
  }
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
  const isWin = process.platform === "win32";
  const p = spawn(cmd, argv, {
    cwd: ROOT,
    env: {
      ...process.env,
      SF_STATE_DIR: stateDir,
      SF_INSTRUCTIONS_PATH: instructionsPath,
      ...env,
    },
    shell: isWin,
    stdio: ["ignore", "inherit", "inherit"],
  });
  kids.push(p);
  p.on("exit", (code, signal) => {
    if (code !== 0 && code !== null && !shuttingDown) {
      console.error(`[schemaforge] backend child process (${cmd}) exited with code ${code} — shutting down stack`);
      cleanupAndExit(code);
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

  try {
    const venvExit = await spawnAwait(py, ["-m", "venv", venvDir], { stdio: "inherit" });
    if (venvExit !== 0) {
      console.error(`[schemaforge] failed to create venv with python interpreter '${py}' (exit code ${venvExit})`);
      process.exit(1);
    }
  } catch (err) {
    console.error(`[schemaforge] failed to run python '${py}': ${err.message}. Please install Python 3.10+ or set SF_PYTHON.`);
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

  try {
    const pipExit = await spawnAwait(venvPip, pipArgs, { stdio: "inherit" });
    if (pipExit !== 0) {
      console.error(`[schemaforge] failed to install dependencies in venv (exit code ${pipExit})`);
      process.exit(1);
    }
  } catch (err) {
    console.error(`[schemaforge] failed to run pip in venv: ${err.message}`);
    process.exit(1);
  }

  writeFileSync(venvReady, "ok");
  console.log("[schemaforge] venv bootstrap complete");
}

// 2. services
let repoRootToken = null;
const repoTokenPath = existsSync(join(REPO_ROOT, ".sf-mcp-token"))
  ? join(REPO_ROOT, ".sf-mcp-token")
  : existsSync(join(ROOT, ".sf-mcp-token"))
  ? join(ROOT, ".sf-mcp-token")
  : null;
if (repoTokenPath) {
  try {
    repoRootToken = readFileSync(repoTokenPath, "utf8").trim();
  } catch {
    // ignore
  }
}
const tokenCandidates = [...new Set([configToken, repoRootToken].filter(Boolean))];

let pgReused = false;
let pgBusy = false;
for (const c of tokenCandidates) {
  const status = await httpProbe("127.0.0.1", Number(pgConfigPort), "/config", 800, {
    Authorization: `Bearer ${c}`,
  });
  if (status === 200) {
    pgReused = true;
    if (c !== configToken) {
      try {
        writeFileSync(tokenFile, c, { mode: 0o600 });
      } catch (err) {
        console.warn(`[schemaforge] failed to write config token file at ${tokenFile}: ${err.message}`);
      }
    }
    console.log(`[schemaforge] reusing running postgres-mcp on :${pgTransportPort} (token verified)`);
    break;
  } else if (status > 0) {
    pgBusy = true;
  }
}

if (!pgReused) {
  const pgTransportStatus = await httpProbe("127.0.0.1", Number(pgTransportPort), "/", 800);
  if (pgBusy || pgTransportStatus > 0) {
    console.error(
      `[schemaforge] postgres-mcp port :${pgTransportPort} is busy with a server whose SF_MCP_CONFIG_TOKEN we cannot verify — stop it, or export SF_MCP_CONFIG_TOKEN matching that server`
    );
    process.exit(1);
  }
  start(venvPy, [join(ROOT, "mcp-servers", "postgres-mcp", "server.py")], {
    SF_CONFIG_PORT: pgConfigPort,
    SF_CONFIG_HOST: "0.0.0.0",
    SF_MCP_CONFIG_TOKEN: configToken,
    PORT: pgTransportPort,
    DATABASE_URL: process.env.DATABASE_URL || "",
  });
}

let ghReused = false;
let ghBusy = false;
for (const c of tokenCandidates) {
  const status = await httpProbe("127.0.0.1", Number(ghConfigPort), "/config", 800, {
    Authorization: `Bearer ${c}`,
  });
  if (status === 200) {
    ghReused = true;
    if (c !== configToken) {
      try {
        writeFileSync(tokenFile, c, { mode: 0o600 });
      } catch (err) {
        console.warn(`[schemaforge] failed to write config token file at ${tokenFile}: ${err.message}`);
      }
    }
    console.log(`[schemaforge] reusing running github-mcp on :${ghTransportPort} (token verified)`);
    break;
  } else if (status > 0) {
    ghBusy = true;
  }
}

if (!ghReused) {
  const ghTransportStatus = await httpProbe("127.0.0.1", Number(ghTransportPort), "/", 800);
  if (ghBusy || ghTransportStatus > 0) {
    console.error(
      `[schemaforge] github-mcp port :${ghTransportPort} is busy with a server whose SF_MCP_CONFIG_TOKEN we cannot verify — stop it, or export SF_MCP_CONFIG_TOKEN matching that server`
    );
    process.exit(1);
  }
  start(venvPy, [join(ROOT, "mcp-servers", "github-mcp", "server.py")], {
    SF_CONFIG_PORT: ghConfigPort,
    SF_CONFIG_HOST: "0.0.0.0",
    SF_MCP_CONFIG_TOKEN: configToken,
    PORT: ghTransportPort,
    GITHUB_PERSONAL_ACCESS_TOKEN: process.env.GITHUB_PERSONAL_ACCESS_TOKEN || "",
  });
}

const regServerFile = join(ROOT, "core", "schemaforge_core", "registry_server.py");
if (await httpProbe("127.0.0.1", Number(regPort), "/health")) {
  console.log(`[schemaforge] reusing running registry on :${regPort}`);
} else if (existsSync(regServerFile)) {
  start(venvPy, ["-m", "schemaforge_core.registry_server"], {
    SF_REGISTRY_PORT: regPort,
    SF_REGISTRY_HOST: "127.0.0.1",
    SF_INSTRUCTIONS_PATH: instructionsPath,
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
    SF_REGISTRY_HOST: "127.0.0.1",
    TRUEFORGE_URL: `http://localhost:${tfPort}`,
  });
}

// 3. TrueForge (standalone) — probe both IPv6 and IPv4, reuse if present
let tfProxyHost = "::1";

if (await httpProbe("::1", Number(tfPort), "/api/v1/capabilities")) {
  tfProxyHost = "::1";
  console.log(`[schemaforge] reusing running TrueForge on [::1]:${tfPort}`);
} else if (await httpProbe("127.0.0.1", Number(tfPort), "/api/v1/capabilities")) {
  tfProxyHost = "127.0.0.1";
  console.log(`[schemaforge] reusing running TrueForge on 127.0.0.1:${tfPort}`);
} else {
  tfProxyHost = tfHost.includes(":") && !tfHost.startsWith("[") ? tfHost : tfHost;
  start("npx", ["@truefoundry/trueforge"], {
    STANDALONE: "true",
    PORT: tfPort,
    HOST: tfHost,
  });
}

// 4. Provision apply-agent (best effort after startup)
async function bootstrapApplyAgent(regPort, maxWaitMs = 15000) {
  const start = Date.now();
  let regUp = false;
  while (Date.now() - start < maxWaitMs) {
    if (await httpProbe("127.0.0.1", Number(regPort), "/health", 500)) {
      regUp = true;
      break;
    }
    await new Promise((r) => setTimeout(r, 400));
  }
  if (!regUp) {
    console.warn("[schemaforge] registry not reachable for agent provisioning");
    return;
  }

  // Small delay for TrueForge backend initialization
  await new Promise((r) => setTimeout(r, 600));

  try {
    const data = JSON.stringify({});
    const res = await new Promise((resolve, reject) => {
      const req = httpRequest(
        {
          host: "127.0.0.1",
          port: Number(regPort),
          path: "/apply-agent",
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Content-Length": Buffer.byteLength(data),
          },
        },
        (res) => {
          let body = "";
          res.on("data", (chunk) => {
            body += chunk;
          });
          res.on("end", () => resolve({ statusCode: res.statusCode, body }));
        }
      );
      req.setTimeout(8000, () => {
        req.destroy();
        reject(new Error("timeout"));
      });
      req.on("error", reject);
      req.write(data);
      req.end();
    });

    if (res.statusCode >= 200 && res.statusCode < 300) {
      console.log("[schemaforge] agent registered successfully (apply-agent)");
    } else {
      console.warn(`[schemaforge] apply-agent non-fatal response (${res.statusCode}): ${res.body}`);
    }
  } catch (err) {
    console.warn(`[schemaforge] apply-agent notice: ${err.message}`);
  }
}

// 5. static UI + proxy
function getProxyTarget(urlPath) {
  const [pathname, search = ""] = urlPath.split("?");
  const query = search ? `?${search}` : "";

  if (pathname === "/api/sf/config/postgres-mcp" || pathname.startsWith("/api/sf/config/postgres-mcp/")) {
    const subpath = pathname.slice("/api/sf/config/postgres-mcp".length) || "/config";
    return {
      host: "127.0.0.1",
      port: Number(pgConfigPort),
      path: subpath + query,
      headers: {
        Authorization: `Bearer ${configToken}`,
      },
    };
  }

  if (pathname === "/api/sf/config/github-mcp" || pathname.startsWith("/api/sf/config/github-mcp/")) {
    const subpath = pathname.slice("/api/sf/config/github-mcp".length) || "/config";
    return {
      host: "127.0.0.1",
      port: Number(ghConfigPort),
      path: subpath + query,
      headers: {
        Authorization: `Bearer ${configToken}`,
      },
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
      host: tfProxyHost,
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

server = createServer((req, res) => {
  const reqUrl = req.url || "/";
  const [pathname] = reqUrl.split("?");

  if (pathname === "/api/sf/config-token") {
    if (existsSync(tokenFile)) {
      try {
        const token = readFileSync(tokenFile, "utf-8").trim();
        res.writeHead(200, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ token }));
        return;
      } catch (err) {
        res.writeHead(500, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: err.message }));
        return;
      }
    } else {
      res.writeHead(404, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ error: "Token not found" }));
      return;
    }
  }

  const target = getProxyTarget(reqUrl);
  if (target) {
    const headers = { ...req.headers, ...(target.headers || {}) };
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

  let reqPath;
  try {
    reqPath = decodeURIComponent((req.url || "/").split("?")[0]);
  } catch (err) {
    if (!res.headersSent) {
      res.writeHead(400, { "Content-Type": "text/plain" });
      res.end("Bad Request: Malformed URI");
    }
    return;
  }

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
  bootstrapApplyAgent(regPort).catch(() => {});
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
