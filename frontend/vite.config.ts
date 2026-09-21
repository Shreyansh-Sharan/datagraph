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
    },
  },
  build: { outDir: "dist", sourcemap: true },
  test: { environment: "jsdom", globals: true, setupFiles: ["src/test/setup.ts"], css: false },
});
