import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In docker compose the api is reachable as http://api:8000; on the host it is published on 8001.
const apiTarget = process.env.API_PROXY_TARGET ?? "http://localhost:8001";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    strictPort: true,
    watch: { usePolling: true },
    proxy: {
      "/api": { target: apiTarget, changeOrigin: true },
    },
  },
});
