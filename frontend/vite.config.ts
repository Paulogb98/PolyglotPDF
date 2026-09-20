import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Development: start the backend with a fixed token and run `npm run dev`:
//   POLYGLOTPDF_APP_TOKEN=dev polyglotpdf app --headless --port 8765
//   POLYGLOTPDF_APP_TOKEN=dev npm --prefix frontend run dev
// (or `python scripts/dev_app.py`, which fixes both the token and the port).
// The proxy adds the token header, so the API works from the Vite dev server.
const token = process.env.POLYGLOTPDF_APP_TOKEN ?? "";
const backend = process.env.POLYGLOTPDF_APP_URL ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  build: {
    // Served by the Python package (polyglotpdf/app/static).
    outDir: fileURLToPath(new URL("../polyglotpdf/app/static", import.meta.url)),
    emptyOutDir: true,
    chunkSizeWarningLimit: 1600,
  },
  server: {
    proxy: {
      "/api": {
        target: backend,
        changeOrigin: true,
        headers: token ? { "x-polyglotpdf-token": token } : {},
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.ts"],
    setupFiles: ["src/test-setup.ts"],
  },
});
