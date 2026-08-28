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
        server.middlewares.use("/api/sf/config-token", (_req, res) => {
          const tokenPath = path.resolve(import.meta.dirname, "../.sf-mcp-token");
          try {
            if (fs.existsSync(tokenPath)) {
              const token = fs.readFileSync(tokenPath, "utf-8").trim();
              res.setHeader("Content-Type", "application/json");
              res.statusCode = 200;
              res.end(JSON.stringify({ token }));
              return;
            }
          } catch {
            // fallback 404
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
        rewrite: (p) => p.replace(/^\/api\/sf\/config\/postgres-mcp/, ""),
      },
      "/api/sf/config/github-mcp": {
        target: "http://127.0.0.1:9002",
        changeOrigin: false,
        rewrite: (p) => p.replace(/^\/api\/sf\/config\/github-mcp/, ""),
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