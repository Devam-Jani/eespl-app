/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In docker compose the api is reachable as http://api:8000; on the host it is published on 8001.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8001";

export default defineConfig({
  plugins: [react()],
  // the visual tests (e2e/) run with Playwright against a running stack, not with vitest
  test: { exclude: ["e2e/**", "node_modules/**", "dist/**"] },
  build: {
    // the design's icons stay files (cached once), not base64 inside the main script
    assetsInlineLimit: (file: string) => (file.endsWith(".svg") ? false : undefined),
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    // a Windows bind mount does not pass file events into the container: polled, but once a second
    // (the default 100 ms kept the dev server at ~11% CPU doing nothing) and not the build output
    watch: { usePolling: true, interval: 1000, binaryInterval: 3000, ignored: ["**/dist/**", "**/node_modules/**"] },
    warmup: { clientFiles: ["./src/main.tsx", "./src/App.tsx", "./src/components/Layout.tsx"] },
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
});
