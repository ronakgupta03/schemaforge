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
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": { target: "http://[::1]:8790", changeOrigin: false },
    },
  },
});