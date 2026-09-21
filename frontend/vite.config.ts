import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// The microfrontend is served by the API under /ui/ in production and proxies
// the REST API during development (ONTOFORGE service on :8765).
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE ?? "/ui/",
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  server: {
    port: 5173,
    proxy: {
      "/api": { target: process.env.VITE_API_TARGET ?? "http://127.0.0.1:8765", changeOrigin: true, rewrite: p => p.replace(/^\/api/, "") },
      // The connection module (mf-studio-connectors hub) runs as its own service; in production the
      // API gateway routes /api/v1/connection-hub to it. Locally /hub stands in for that route.
      "/hub": { target: process.env.VITE_HUB_TARGET ?? "http://127.0.0.1:8025", changeOrigin: true, rewrite: p => p.replace(/^\/hub/, "") },
    },
  },
  build: { outDir: "dist", sourcemap: true },
  // tests never read .env.local: they run against the mock adapter with the connection module unset
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], css: false, env: { VITE_API_MODE: "mock", VITE_CONNECTIONS_URL: "", VITE_HUB_TARGET: "" } },
});
