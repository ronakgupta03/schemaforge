import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import fs from "node:fs";
import path from "node:path";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    {
      name: "sf-config-token",
      configureServer(server) {
        server.middlewares.use("/api/sf/config-token", (req, res) => {
          const host = (req.headers.host || "").toLowerCase();
          const isLoopback =
            host === "localhost" ||
            host.startsWith("localhost:") ||
            host === "127.0.0.1" ||
            host.startsWith("127.0.0.1:") ||
            host === "[::1]" ||
            host.startsWith("[::1]:");
          if (!isLoopback) {
            res.statusCode = 403;
            res.setHeader("Content-Type", "application/json");
            res.end(JSON.stringify({ error: "Forbidden: loopback only" }));
            return;
          }
          const candidates = [
            path.resolve(import.meta.dirname, "../.sf-mcp-token"),
            path.resolve(process.env.HOME || process.env.USERPROFILE || ".", ".schemaforge", "sf-mcp-token"),
            path.resolve(process.env.SF_STATE_DIR || "", "sf-mcp-token"),
          ];
          for (const tokenPath of candidates) {
            try {
              if (tokenPath && fs.existsSync(tokenPath)) {
                const token = fs.readFileSync(tokenPath, "utf-8").trim();
                if (token) {
                  res.setHeader("Content-Type", "application/json");
                  res.statusCode = 200;
                  res.end(JSON.stringify({ token }));
                  return;
                }
              }
            } catch {
              // fallback
            }
          }
          res.statusCode = 404;
          res.setHeader("Content-Type", "application/json");
          res.end(JSON.stringify({ error: "Token not found" }));
        });
      },
    },
  ],
  resolve: {
    dedupe: [
      "@assistant-ui/core",
      "@assistant-ui/react",
      "@assistant-ui/tap",
      "@assistant-ui/store",
      "react",
      "react-dom",
    ],
  },
  build: {
    // Cloudflare deploy: /assets/* is routed to the TrueForge container (its
    // UI references absolute /assets/*), so the SPA's own bundles live under
    // /static/* to avoid the collision.
    assetsDir: "static",
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api/sf/config/postgres-mcp": {
        target: "http://127.0.0.1:9001",
        changeOrigin: false,
        rewrite: (p) => p.replace(/^\/api\/sf\/config\/postgres-mcp(\/config)?/, "/config"),
      },
      "/api/sf/config/github-mcp": {
        target: "http://127.0.0.1:9002",
        changeOrigin: false,
        rewrite: (p) => p.replace(/^\/api\/sf\/config\/github-mcp(\/config)?/, "/config"),
      },
      "/api/sf": {
        target: "http://127.0.0.1:9010",
        changeOrigin: false,
        rewrite: (p) => p.replace(/^\/api\/sf/, ""),
      },
      "/api": { target: "http://[::1]:8790", changeOrigin: false },
    },
  },
});