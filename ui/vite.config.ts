import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
      "/api/sf/config/postgres-mcp": { target: "http://127.0.0.1:9001", changeOrigin: false },
      "/api/sf/config/github-mcp": { target: "http://127.0.0.1:9002", changeOrigin: false },
      "/api/sf": { target: "http://127.0.0.1:9010", changeOrigin: false },
      "/api": { target: "http://[::1]:8790", changeOrigin: false },
    },
  },
});